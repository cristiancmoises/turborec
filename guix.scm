;;; guix.scm — GNU Guix package definition for Turbo Recorder.
;;;
;;; Build a local binary:        guix build -f guix.scm
;;; Install into your profile:   guix package -f guix.scm
;;; Relocatable binary tarball:  guix pack -RR -S /bin=bin -e '(load "guix.scm")'
;;;
;;; This installs the `turborec` (Python CLI) and `turborecorder` (shell CLI)
;;; recorders with ffmpeg, wf-recorder (Wayland) and pulseaudio wrapped onto
;;; PATH, so screen/audio recording and OBS-style YouTube streaming work out of
;;; the box.  The Tk GUI needs a Tk-enabled Python; Guix's default `python`
;;; omits `_tkinter`, so on Guix use the CLI (`turborec record …`) — or the GUI
;;; launcher documented in docs/TUTORIAL.md (§1, "GNU Guix").

(use-modules (guix packages)
             (guix build-system copy)
             (guix gexp)
             (guix git-download)
             ((guix licenses) #:prefix license:)
             (gnu packages bash)
             (gnu packages python)
             (gnu packages pulseaudio)
             (gnu packages video))

(define %source-dir (dirname (current-filename)))

(define turborec
  (package
    (name "turborec")
    (version "3.4.0")
    (source (local-file %source-dir "turborec-checkout"
                        #:recursive? #t
                        #:select? (or (git-predicate %source-dir)
                                      (const #t))))
    (build-system copy-build-system)
    (arguments
     (list
      #:install-plan
      #~'(("turborec.py"   "bin/turborec")
          ("turborecorder" "bin/turborecorder"))
      #:phases
      #~(modify-phases %standard-phases
          (add-after 'install 'patch-and-wrap
            (lambda* (#:key inputs outputs #:allow-other-keys)
              (let* ((out    (assoc-ref outputs "out"))
                     (bin    (string-append out "/bin"))
                     (sh     (search-input-file inputs "/bin/bash"))
                     (python (dirname (search-input-file inputs "/bin/python3")))
                     (tools  (map (lambda (pkg)
                                    (string-append (assoc-ref inputs pkg) "/bin"))
                                  '("ffmpeg" "wf-recorder" "pulseaudio")))
                     (progs  (list (string-append bin "/turborec")
                                   (string-append bin "/turborecorder"))))
                ;; Run each front-end under a hermetic PATH (its own python3,
                ;; ffmpeg, wf-recorder and pactl), so it works regardless of the
                ;; user's environment.
                (for-each
                 (lambda (f)
                   (chmod f #o755)
                   (patch-shebang f)
                   (wrap-program f
                     #:sh sh
                     `("PATH" ":" prefix ,(cons python tools))))
                 progs)))))))
    (inputs (list bash-minimal ffmpeg wf-recorder pulseaudio python))
    (home-page "https://github.com/cristiancmoises/turborec")
    (synopsis "State-of-the-art hardware-accelerated screen and audio recorder")
    (description
     "Turbo Recorder captures your screen and audio at the best quality your
hardware can deliver.  It auto-detects the operating system, display server,
CPU/GPU, the best hardware video encoder, screen resolution and audio devices,
then records or live-streams (OBS-style RTMP to YouTube) with a quality-first
FFmpeg pipeline.  It ships two front-ends over one engine: the cross-platform
@code{turborec} (Python CLI, plus a Tk GUI where a Tk-enabled Python is present)
and the lightweight @code{turborecorder} shell CLI for X11.")
    (license license:gpl3+)))

turborec
