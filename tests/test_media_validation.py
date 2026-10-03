"""Synthetic completed files and probe processes; never capture user devices."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import turborec as tr


class MediaValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / "recording.mkv"
        self.output.write_bytes(b"nonempty, but not necessarily playable")
        self.intermediate = self.directory / "recoverable.mkv"
        self.intermediate.write_bytes(b"intermediate frames")
        self.plan = tr.RecordPlan(str(self.output), cleanup=[str(self.intermediate)])

    def finish(self, metadata):
        # The native process is the external boundary. Finalization, parsing,
        # recovery and the GUI status all stay real.
        result = (0, json.dumps(metadata))
        with mock.patch.object(tr, "_run_media_probe", return_value=result, create=True), \
                mock.patch.object(tr, "_run_bounded_command", return_value=(0,
                    "frame=1\nout_time_us=43478\nprogress=end\n")):
            return tr._finalize_recording(self.plan, [], [])

    def test_zero_duration_nonempty_video_fails_shared_finalization_and_preserves_media(self):
        code, detail = self.finish({"streams": [{"codec_type": "video", "duration": "0.000000"}],
                                  "format": {"duration": "0.000000"},
                                  "packets": [{"pts_time": "0.000000", "duration_time": "0.000000"}]})
        self.assertNotEqual(code, 0)
        self.assertNotIn("Saved", tr._recording_status(self.plan, code))
        self.assertIn("Recoverable", detail)
        self.assertTrue(self.output.exists())
        self.assertTrue(self.intermediate.exists())

    def test_positive_audio_container_duration_cannot_hide_zero_duration_video(self):
        self.plan.media_audio = True
        video = {"streams": [{"codec_type": "video", "duration": "0.000000"}],
                 "format": {"duration": "0.042667"}}
        audio = {"streams": [{"codec_type": "audio", "duration": "0.042667"}]}
        with mock.patch.object(tr, "_run_media_probe", side_effect=[(0, json.dumps(video)), (0, json.dumps(audio))]), \
                mock.patch.object(tr, "_run_bounded_command", return_value=(0,
                    "frame=1\nout_time_us=42667\nprogress=end\n")):
            code, detail = tr._finalize_recording(self.plan, [], [])
        self.assertNotEqual(code, 0)
        self.assertNotIn("Saved", tr._recording_status(self.plan, code))
        self.assertIn("positive media duration", detail)
        self.assertTrue(self.output.exists())
        self.assertTrue(self.intermediate.exists())

    def test_zero_exit_cli_does_not_save_or_open_unusable_video(self):
        self.plan.procs = [("synthetic", [sys.executable, "-c", "pass"], "q")]
        with mock.patch.object(tr, "_run_media_probe", return_value=(0, '{"streams":[]}'), create=True), \
                mock.patch.object(tr, "open_file") as opener, redirect_stderr(io.StringIO()) as messages:
            code = tr.record_plan(self.plan, open_when_done=True)
        self.assertNotEqual(code, 0)
        self.assertNotIn("Saved", messages.getvalue())
        self.assertFalse(opener.called)
        self.assertTrue(self.intermediate.exists())

    def test_positive_short_video_saves_and_cleans_only_after_validation(self):
        code, _ = self.finish({"streams": [{"codec_type": "video", "duration": "0.043478"}],
                               "format": {"duration": "0.043478"}})
        self.assertEqual(code, 0)
        self.assertIn("Saved", tr._recording_status(self.plan, code))
        self.assertTrue(self.output.exists())
        self.assertFalse(self.intermediate.exists())

    def test_unknown_container_duration_uses_positive_packet_timeline(self):
        code, _ = self.finish({"streams": [{"codec_type": "video"}], "format": {},
            "packets": [{"pts_time": "-0.086957", "duration_time": "0.043478"},
                        {"pts_time": "-0.043478", "duration_time": "0.043478"}]})
        self.assertEqual(code, 0)

    def test_audio_only_requires_audio_and_accepts_positive_duration(self):
        self.plan.is_video = False
        code, _ = self.finish({"streams": [{"codec_type": "audio", "duration": "0.020000"}]})
        self.assertEqual(code, 0)
        code, _ = self.finish({"streams": [{"codec_type": "video", "duration": "1.000000"}]})
        self.assertNotEqual(code, 0)

    def test_requested_audio_cannot_disappear_from_an_otherwise_valid_video(self):
        self.plan.media_audio = True
        with mock.patch.object(tr, "_run_media_probe", side_effect=[
                (0, '{"streams":[{"codec_type":"video","duration":"1"}]}'),
                (0, '{"streams":[]}')], create=True), \
                mock.patch.object(tr, "_run_bounded_command", return_value=(0, "frame=1\n")):
            code, detail = tr._finalize_recording(self.plan, [], [])
        self.assertNotEqual(code, 0)
        self.assertIn("audio", detail)
        self.assertTrue(self.intermediate.exists())

    def test_absent_invalid_or_nonfinite_metadata_never_means_success(self):
        for metadata in ({}, {"streams": []}, {"streams": [{"codec_type": "audio"}], "format": {"duration": "1"}},
                         {"streams": [{"codec_type": "video", "duration": "NaN"}]},
                         {"streams": [{"codec_type": "video"}], "format": {"duration": "Infinity"}}):
            with self.subTest(metadata=metadata):
                code, _ = self.finish(metadata)
                self.assertNotEqual(code, 0)

    def test_probe_failure_preserves_output_with_actionable_reason(self):
        with mock.patch.object(tr, "_run_media_probe", return_value=(1, ""), create=True):
            code, detail = tr._finalize_recording(self.plan, [], [])
        self.assertNotEqual(code, 0)
        self.assertIn("validation", detail.lower())
        self.assertTrue(self.intermediate.exists())

    def test_invalid_encoded_frames_fail_even_with_positive_metadata(self):
        metadata = {"streams": [{"codec_type": "video", "duration": "1.0"}]}
        with mock.patch.object(tr, "_run_media_probe", return_value=(0, json.dumps(metadata)), create=True), \
                mock.patch.object(tr, "_run_bounded_command", return_value=(1, "invalid frame")):
            code, detail = tr._finalize_recording(self.plan, [], [])
        self.assertNotEqual(code, 0)
        self.assertIn("invalid frame", detail)
        self.assertTrue(self.intermediate.exists())

    def test_successful_decoder_without_frames_is_not_a_successful_recording(self):
        metadata = {"streams": [{"codec_type": "video", "duration": "1.0"}]}
        with mock.patch.object(tr, "_run_media_probe", return_value=(0, json.dumps(metadata)), create=True), \
                mock.patch.object(tr, "_run_bounded_command", return_value=(0, "frame=0\nprogress=end\n")):
            code, _ = tr._finalize_recording(self.plan, [], [])
        self.assertNotEqual(code, 0)
        self.assertTrue(self.intermediate.exists())

    def test_missing_matching_probe_does_not_use_unrelated_path_tool(self):
        self.plan.media_ffmpeg = str(self.directory / "missing" / "ffmpeg")
        with mock.patch.object(tr.shutil, "which", side_effect=AssertionError("unrelated PATH fallback")):
            code, detail = tr._finalize_recording(self.plan, [], [])
        self.assertNotEqual(code, 0)
        self.assertIn("ffprobe", detail)
        self.assertTrue(self.intermediate.exists())

    def test_streams_do_not_probe_or_decode_local_files(self):
        self.plan.is_stream = True
        with mock.patch.object(tr, "_run_media_probe", side_effect=AssertionError("stream probed"), create=True):
            code, _ = tr._finalize_recording(self.plan, [], [])
        self.assertEqual(code, 0)


class ProbeProcessTests(unittest.TestCase):
    def test_probe_stdout_is_capped_and_overflow_denied(self):
        code, output = tr._run_media_probe([sys.executable, "-c",
            "import os; os.write(1, b'x' * 1000000)"], timeout=3)
        self.assertNotEqual(code, 0)
        self.assertLessEqual(len(output), 65536)

    def test_probe_timeout_kills_and_reaps_owned_child(self):
        code, _ = tr._run_media_probe([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)
        self.assertNotEqual(code, 0)

    def test_probe_preserves_small_json_and_nonzero_status(self):
        code, output = tr._run_media_probe([sys.executable, "-c",
            "print('{\"streams\":[]}'); raise SystemExit(7)"], timeout=3)
        self.assertEqual(code, 7)
        self.assertEqual(json.loads(output), {"streams": []})


if __name__ == "__main__":
    unittest.main()
