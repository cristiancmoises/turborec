;;; guix.scm — GNU Guix package definition for Turbo Recorder.
;;;
;;; Build a local binary:        guix build -f guix.scm
;;; Install into your profile:   guix package -f guix.scm
;;; Relocatable payload:        guix pack -RR -S /bin=bin -e '(load "guix.scm")'
;;; Public releases wrap the uncompressed TAR payload in a .zupt archive.
;;;
;;; This installs the `turborec` (Python CLI) and `turborecorder` (shell CLI)
;;; recorders with ffmpeg, wf-recorder (Wayland) and pulseaudio wrapped onto
;;; PATH, so screen/audio recording and OBS-style YouTube streaming work out of
;;; the box.  Python's separate `tk` output is included and wrapped onto
;;; GUIX_PYTHONPATH, so `turborec gui` works from a profile or Guix pack.

(use-modules (guix packages)
             (guix build-system copy)
             (guix gexp)
             (guix git-download)
             ((guix licenses)
              #:prefix license:)
             (gnu packages base)
             (gnu packages bash)
             (gnu packages freedesktop)
             (gnu packages gawk)
             (gnu packages pciutils)
             (gnu packages python)
             (gnu packages pulseaudio)
             (gnu packages video)
             (gnu packages window-management)
             (gnu packages xdisorg)
             (gnu packages xorg))

(define %source-dir
  (dirname (current-filename)))

(define turborec
  (package
    (name "turborec")
    (version "3.10.1")
    (source
     (let ((tracked? (git-predicate %source-dir)))
       (local-file %source-dir
                   "turborec-checkout"
                   #:recursive? #t
                   ;; Only version-controlled project inputs enter the store.
                   ;; Local notes, issue archives and credentials stay private.
                   #:select? tracked?)))
    (build-system copy-build-system)
    (arguments
     (list
      #:install-plan
      #~'(("turborec.py" "bin/turborec")
          ("turborecorder" "bin/turborecorder")
          ("packaging/turborec.desktop" "share/applications/turborec.desktop")
          ("packaging/turborec.svg"
           "share/icons/hicolor/scalable/apps/turborec.svg")
          ("README.md" "share/doc/turborec/README.md")
          ("CHANGELOG.md" "share/doc/turborec/CHANGELOG.md")
          ("SECURITY.md" "share/doc/turborec/SECURITY.md")
          ("docs/TUTORIAL.md" "share/doc/turborec/docs/TUTORIAL.md")
          ("docs/README.pt-BR.md" "share/doc/turborec/docs/README.pt-BR.md")
          ("docs/turborec-gui.png" "share/doc/turborec/docs/turborec-gui.png"))
      #:phases
      #~(modify-phases %standard-phases
          (add-after 'unpack 'check
            (lambda* (#:key inputs tests? #:allow-other-keys)
              (when tests?
                (let ((python-tk (dirname (car (find-files (assoc-ref inputs
                                                            "python:tk")
                                                           "^_tkinter.*\\.so$")))))
                  (setenv "GUIX_PYTHONPATH" python-tk)
                  (invoke "python3" "-m" "py_compile" "turborec.py")
                  (invoke "python3"
                          "-m"
                          "unittest"
                          "discover"
                          "-s"
                          "tests"
                          "-v")
                  (invoke "python3" "-c"
                          "import _tkinter, tkinter; tkinter.Tcl()")
                  (invoke "bash" "-n" "turborecorder")
                  (invoke "desktop-file-validate" "packaging/turborec.desktop")))))
          (add-after 'install 'patch-and-wrap
            (lambda* (#:key inputs outputs #:allow-other-keys)
              (define (command-directory command)
                (dirname (search-input-file inputs
                                            (string-append "/bin/" command))))

              (let* ((out (assoc-ref outputs "out"))
                     (bin (string-append out "/bin"))
                     (sh (search-input-file inputs "/bin/bash"))
                     (turborec (string-append bin "/turborec"))
                     (turborecorder (string-append bin "/turborecorder"))
                     (python-tk (dirname (car (find-files (assoc-ref inputs
                                                           "python:tk")
                                                          "^_tkinter.*\\.so$"))))
                     (path (map command-directory
                                '("awk" "bash"
                                  "cat"
                                  "date"
                                  "ffmpeg"
                                  "grep"
                                  "head"
                                  "lspci"
                                  "mkdir"
                                  "pactl"
                                  "python3"
                                  "sed"
                                  "sh"
                                  "tr"
                                  "wf-recorder"
                                  "wlr-randr"
                                  "wmctrl"
                                  "xdg-open"
                                  "xdpyinfo"
                                  "xrandr"))))
                (for-each (lambda (program)
                            (chmod program #o755)
                            (patch-shebang program))
                          (list turborec turborecorder))
                (wrap-program turborec
                  #:sh sh
                  `("PATH" ":" prefix
                    ,path)
                  `("GUIX_PYTHONPATH" ":" prefix
                    (,python-tk)))
                (wrap-program turborecorder
                  #:sh sh
                  `("PATH" ":" prefix
                    ,path)))))
          (add-after 'patch-and-wrap 'check-installed-commands
            (lambda _
              (invoke (string-append #$output "/bin/turborec") "--version")
              (invoke (string-append #$output "/bin/turborecorder") "-h"))))))
    (native-inputs (list desktop-file-utils))
    (inputs `(("bash-minimal" ,bash-minimal)
              ("coreutils-minimal" ,coreutils-minimal)
              ("ffmpeg" ,ffmpeg)
              ("gawk" ,gawk)
              ("grep" ,grep)
              ("pciutils" ,pciutils)
              ("pulseaudio" ,pulseaudio)
              ("python" ,python)
              ("python:tk" ,python "tk")
              ("sed" ,sed)
              ("wf-recorder" ,wf-recorder)
              ("wlr-randr" ,wlr-randr)
              ("wmctrl" ,wmctrl)
              ("xdg-utils" ,xdg-utils)
              ("xdpyinfo" ,xdpyinfo)
              ("xrandr" ,xrandr)))
    (home-page "https://github.com/cristiancmoises/turborec")
    (synopsis "Screen and audio recorder using FFmpeg")
    (description
     "Turbo Recorder captures the screen, microphone, and system audio using
FFmpeg.  It detects available hardware video encoders and falls back to
software encoding when needed.  Its Python front-end provides a command-line
interface and a Tk graphical interface, while @command{turborecorder} provides
a Bash interface.  X11 capture uses FFmpeg directly; wlroots-based Wayland
capture uses @command{wf-recorder}.  The program can also capture individual
monitors, windows, or regions, overlay a camera, and stream over RTMP.")
    (license license:gpl3)))

turborec
