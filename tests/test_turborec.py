import io
import subprocess
import sys
import unittest
from unittest import mock

import turborec as tr


DSHOW_SOURCES = r"""
Auto-detected sources for dshow:
  @device_pnp_\\?\usb#vid_045e&pid_0779\global [Microsoft® LifeCam HD-3000] (video)
  @device_cm_{33D9A762}\wave_{MIC} [Matriz de microfone (Intel® SST)] (audio)
  @device_cm_{33D9A762}\wave_{MIX} [Mixagem estéreo (Realtek Áudio)] (audio)
  @device_pnp_\\?\usb#capture\global [Placa de captura] (video, audio)
"""

DSHOW_LEGACY = r"""
[dshow @ 000001] DirectShow video devices (some may be both video and audio devices)
[dshow @ 000001]  "Câmera HD®" (video)
[dshow @ 000001]     Alternative name "@device_pnp_cam"
[dshow @ 000001] DirectShow audio devices
[dshow @ 000001]  "Matriz de microfone (Intel® SST)" (audio)
[dshow @ 000001]     Alternative name "@device_cm_mic"
"""


class CommandOutputTests(unittest.TestCase):
    def test_decodes_ffmpeg_utf8_instead_of_windows_ansi(self):
        raw = "Câmera 日本語 Intel®".encode("utf-8")
        self.assertEqual(tr._decode_command_output(raw), "Câmera 日本語 Intel®")

    def test_timeout_preserves_partial_device_output(self):
        exc = subprocess.TimeoutExpired(
            ["ffmpeg"], 25, output="Mixagem estéreo".encode("utf-8"))
        with mock.patch.object(tr.subprocess, "run", side_effect=exc):
            self.assertEqual(
                tr.run_cmd(["ffmpeg"], timeout=25), "Mixagem estéreo")


class DirectShowParserTests(unittest.TestCase):
    def test_structured_sources_keep_unique_ids_labels_and_types(self):
        devices = tr._parse_dshow_sources(DSHOW_SOURCES)
        self.assertEqual(len(devices), 4)
        mic = next(d for d in devices if "Matriz" in d.label)
        self.assertTrue(mic.id.startswith("@device_cm_"))
        self.assertEqual(mic.media_types, {"audio"})
        capture = next(d for d in devices if d.label == "Placa de captura")
        self.assertEqual(capture.media_types, {"audio", "video"})

    def test_legacy_alternative_names_are_paired_not_duplicated(self):
        devices = tr._parse_dshow_list_devices(DSHOW_LEGACY)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].label, "Câmera HD®")
        self.assertEqual(devices[0].id, "@device_pnp_cam")
        self.assertEqual(devices[1].id, "@device_cm_mic")

    def test_ffmpeg8_inline_listing_without_headings(self):
        text = r"""
[dshow @ 123] "USB Camera" (video)
[dshow @ 123]  Alternative name "@device_pnp_camera"
[dshow @ 123] "Micrófono" (audio)
[dshow @ 123]  Alternative name "@device_cm_microphone"
"""
        devices = tr._parse_dshow_list_devices(text)
        self.assertEqual(
            [(d.label, d.id, d.media_types) for d in devices],
            [
                ("USB Camera", "@device_pnp_camera", {"video"}),
                ("Micrófono", "@device_cm_microphone", {"audio"}),
            ],
        )

    def test_duplicate_friendly_names_remain_distinct_by_id(self):
        text = """
  @device_cm_one [Microphone] (audio)
  @device_cm_two [Microphone] (audio)
"""
        devices = tr._parse_dshow_sources(text)
        self.assertEqual([d.id for d in devices],
                         ["@device_cm_one", "@device_cm_two"])

    def test_ptbr_loopback_is_recognized_but_virtual_mic_is_not(self):
        self.assertTrue(
            tr._is_windows_loopback("Mixagem estéreo (Realtek Áudio)"))
        self.assertFalse(
            tr._is_windows_loopback("Microfone virtual (NVIDIA Broadcast)"))

    def test_audio_and_camera_commands_use_stable_ids(self):
        si = tr.SystemInfo(os="windows")
        dev = tr.AudioDevice("@device_cm_mic", "Matriz de microfone")
        audio = tr.audio_input_args(si, dev)
        self.assertIn("audio=@device_cm_mic", audio)

        spec = tr.RecordSpec(mode="video_only", camera="@device_pnp_camera")
        camera = tr.camera_input_args(si, spec)
        self.assertIn("video=@device_pnp_camera", camera)

    def test_duplicate_gui_labels_keep_both_stable_devices(self):
        devices = [
            tr.AudioDevice("@device_one", "Microphone"),
            tr.AudioDevice("@device_two", "Microphone"),
        ]
        choices = tr._label_choice_map(devices)
        self.assertEqual(list(choices), ["Microphone [1]", "Microphone [2]"])
        self.assertEqual(
            [device.id for device in choices.values()],
            ["@device_one", "@device_two"],
        )


class CaptureTargetTests(unittest.TestCase):
    def setUp(self):
        self.enc = tr.EncoderChoice("libx264", "software", "h264")

    def test_signed_geometry_round_trip(self):
        self.assertEqual(
            tr._parse_geometry("1920x1080-1920+0"),
            ("1920x1080", -1920, 0),
        )
        self.assertEqual(
            tr._parse_wxhxy("800x600+0-600"),
            (800, 600, 0, -600),
        )

    def test_windows_negative_offsets_reach_gdigrab(self):
        si = tr.SystemInfo(os="windows", screen="3840x1080")
        _pre, args = tr.screen_input_args(
            si, 60, "1920x1080-1920+0", self.enc)
        self.assertIn("-1920", args)
        self.assertEqual(args[-1], "desktop")

    def test_x11_negative_offset_keeps_required_plus_separator(self):
        si = tr.SystemInfo(os="linux", display_server="x11")
        with mock.patch.dict(tr.os.environ, {"DISPLAY": ":0.0"}):
            _pre, args = tr.screen_input_args(
                si, 60, "1920x1080-1920+0", self.enc)
        self.assertEqual(args[-1], ":0.0+-1920,0")

    def test_windows_hwnd_is_preferred_over_unicode_title(self):
        si = tr.SystemInfo(os="windows")
        _pre, args = tr.screen_input_args(
            si, 30, None, self.enc,
            win_title="Câmera 日本語", win_hwnd="0x1234")
        self.assertEqual(args[-2:], ["-i", "hwnd=0x1234"])
        self.assertNotIn("title=Câmera 日本語", args)

    @unittest.skipUnless(sys.platform == "win32", "requires Win32 APIs")
    def test_windows_native_monitor_enumeration(self):
        monitors = tr._detect_monitors_windows()
        self.assertTrue(monitors)
        self.assertTrue(monitors[0].geometry)

    def test_macos_uses_enumerated_screen_index(self):
        si = tr.SystemInfo(os="macos")
        _pre, args = tr.screen_input_args(
            si, 30, None, self.enc, screen_device="3")
        self.assertEqual(args[-1], "3:none")

    def test_macos_display_detection_ignores_camera_indices(self):
        video = [
            "0: FaceTime HD Camera",
            "1: OBS Virtual Camera",
            "2: Capture screen 0",
            "3: Capture screen 1",
        ]
        with mock.patch.object(
                tr, "_enumerate_avfoundation", return_value=(video, [])):
            targets = tr._detect_displays_macos("ffmpeg")
        self.assertEqual([t.input_id for t in targets], ["2", "3"])

    def test_macos_region_uses_real_screen_and_crop_filter(self):
        si = tr.SystemInfo(
            os="macos", screen="1920x1080",
            encoders={"libx264"}, ffmpeg="ffmpeg")
        spec = tr.RecordSpec(
            mode="video_only", geometry="800x600+100+50",
            screen_device="3", out_dir="/unused")
        with mock.patch.object(tr, "ensure_dir"):
            cmd, _out = tr.build_command(si, spec)
        self.assertIn("3:none", cmd)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("crop=800:600:100:50", graph)

    def test_malformed_region_fails_instead_of_capturing_full_screen(self):
        si = tr.SystemInfo(os="windows")
        spec = tr.RecordSpec(mode="video_only", region="not-a-region")
        with self.assertRaises(SystemExit):
            tr._validate_capture_geometry(si, spec)


class DefaultsAndShutdownTests(unittest.TestCase):
    def test_auto_mode_degrades_to_available_sources(self):
        mic = tr.AudioDevice("mic", "Mic")
        mon = tr.AudioDevice("mon", "System", True)
        self.assertEqual(
            tr._automatic_mode(
                tr.SystemInfo(default_mic=mic, default_monitor=mon)),
            "video_both",
        )
        self.assertEqual(
            tr._automatic_mode(tr.SystemInfo(default_mic=mic)), "video_mic")
        self.assertEqual(
            tr._automatic_mode(tr.SystemInfo(default_monitor=mon)),
            "video_system",
        )
        self.assertEqual(
            tr._automatic_mode(tr.SystemInfo()), "video_only")

    def test_auto_mode_uses_manually_resolved_device(self):
        args = tr.build_parser().parse_args(
            ["record", "--mic-device", "@manual_mic", "--dry-run"])
        si = tr.SystemInfo(os="windows")
        captured = {}

        def fake_build(_si, spec, preview=False):
            captured["spec"] = spec
            return tr.RecordPlan("unused", [])

        with mock.patch.object(tr, "probe_system", return_value=si), \
                mock.patch.object(tr, "_resolve_capture_target", return_value=None), \
                mock.patch.object(tr, "build_plan", side_effect=fake_build), \
                mock.patch.object(tr, "record_plan", return_value=0):
            self.assertEqual(tr.cmd_record(args), 0)
        self.assertEqual(captured["spec"].mode, "video_mic")

    def test_linux_without_pactl_does_not_invent_audio_devices(self):
        with mock.patch.object(tr.shutil, "which", return_value=None):
            mics, monitors, default_mic, default_monitor = tr._detect_audio_linux()
        self.assertEqual((mics, monitors, default_mic, default_monitor),
                         ([], [], None, None))

    def test_explicit_missing_system_audio_still_fails(self):
        si = tr.SystemInfo(os="windows", encoders={"libx264"})
        spec = tr.RecordSpec(mode="video_system")
        with self.assertRaises(SystemExit):
            tr.build_plan(si, spec, preview=True)

    def test_ffmpeg_stop_writes_q_instead_of_sending_signal(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.stdin = io.BytesIO()
        tr._signal_stop(proc, "q")
        self.assertEqual(proc.stdin.getvalue(), b"q")
        proc.send_signal.assert_not_called()

    def test_unusable_advertised_hardware_falls_back_to_software(self):
        si = tr.SystemInfo(
            os="windows", gpu_vendor="nvidia",
            encoders={"h264_nvenc", "libx264"})
        with mock.patch.object(
                tr, "_hardware_encoder_usable", return_value=False):
            choice = tr.choose_encoder(si, "h264")
        self.assertEqual((choice.name, choice.kind), ("libx264", "software"))

    def test_hybrid_windows_tries_another_gpu_before_software(self):
        si = tr.SystemInfo(
            os="windows", gpu_vendor="nvidia", has_gpu=True,
            encoders={"h264_nvenc", "h264_qsv", "libx264"})
        with mock.patch.object(
                tr, "_hardware_encoder_usable",
                side_effect=lambda _si, name, _kind: name == "h264_qsv"):
            choice = tr.choose_encoder(si, "h264")
        self.assertEqual((choice.name, choice.kind), ("h264_qsv", "qsv"))


if __name__ == "__main__":
    unittest.main()
