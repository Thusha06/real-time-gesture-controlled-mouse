const cameraIndicator = document.querySelector("#camera-indicator");
const micIndicator = document.querySelector("#mic-indicator");
const gestureButton = document.querySelector("#gesture-toggle");
const voiceButton = document.querySelector("#voice-toggle");
const gestureLabel = document.querySelector("#gesture-label");
const voiceLabel = document.querySelector("#voice-label");
const cursor = document.querySelector("#web-cursor");
const toast = document.querySelector("#toast");
const setupOverlay = document.querySelector("#setup-overlay");

let cameraStream = null;
let microphoneStream = null;
let handTracker = null;
let trackingVideo = null;
let trackingActive = false;
let inferencePending = false;
let recognition = null;
let listening = false;
let lastScrollTime = 0;
let toastTimeout;

document.querySelector("#today-label").textContent = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
}).format(new Date());
document.querySelector("#copyright-year").textContent = `© ${new Date().getFullYear()} Nexora`;

function setActivity(title, message, active = false) {
  document.querySelector("#status-title").textContent = title;
  document.querySelector("#status-message").textContent = message;
  document.querySelector("#status-badge-text").textContent = active ? "CONNECTED" : "STANDING BY";
  document.querySelector(".status-badge").classList.toggle("is-active", active);
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimeout);
  toastTimeout = window.setTimeout(() => toast.classList.remove("visible"), 3000);
}

function setCameraStatus(enabled) {
  cameraIndicator.classList.toggle("is-on", enabled);
  document.querySelector("#camera-note").textContent = enabled ? "Camera connected" : "Camera permission needed";
  gestureLabel.textContent = enabled ? "Turn gesture control off" : "Connect webcam";
}

function setMicStatus(enabled) {
  micIndicator.classList.toggle("is-on", enabled);
  document.querySelector("#mic-note").textContent = enabled ? "Microphone connected" : "Microphone permission needed";
  voiceLabel.textContent = enabled ? (listening ? "Stop listening" : "Start listening") : "Connect microphone";
}

function openSetup() {
  setupOverlay.classList.add("open");
  setupOverlay.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  setupOverlay.querySelector(".dialog-close").focus();
}

function closeSetup() {
  setupOverlay.classList.remove("open");
  setupOverlay.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

document.querySelector("#open-setup").addEventListener("click", openSetup);
document.querySelector("#footer-setup").addEventListener("click", openSetup);
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", closeSetup));
setupOverlay.addEventListener("click", (event) => {
  if (event.target === setupOverlay) closeSetup();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && setupOverlay.classList.contains("open")) closeSetup();
});
document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", () => {
    document.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
    link.classList.add("active");
  });
});

function stopGestureControl() {
  trackingActive = false;
  inferencePending = false;
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
  if (trackingVideo) {
    trackingVideo.pause();
    trackingVideo.srcObject = null;
    trackingVideo = null;
  }
  document.querySelector("#camera-float").classList.remove("visible");
  if (handTracker) {
    handTracker.close().catch(() => {});
    handTracker = null;
  }
  cursor.classList.remove("visible", "pinch");
  document.body.classList.remove("gesture-mode-active");
  setCameraStatus(false);
  gestureButton.disabled = false;
  gestureButton.setAttribute("aria-pressed", "false");
}

function findClickableElement(x, y) {
  const element = document.elementFromPoint(x, y);
  if (!element) return null;
  return element.closest("button:not(:disabled), a[href], [role='button'], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)");
}

function handleHandResults(results) {
  if (!trackingActive) return;
  const landmarks = results.multiHandLandmarks?.[0];
  if (!landmarks) {
    cursor.classList.remove("visible", "pinch");
    return;
  }

  const indexTip = landmarks[8];
  const thumbTip = landmarks[4];
  const x = Math.max(8, Math.min(window.innerWidth - 8, (1 - indexTip.x) * window.innerWidth));
  const y = Math.max(8, Math.min(window.innerHeight - 8, indexTip.y * window.innerHeight));
  cursor.style.left = `${x}px`;
  cursor.style.top = `${y}px`;
  cursor.classList.add("visible");

  const dx = thumbTip.x - indexTip.x;
  const dy = thumbTip.y - indexTip.y;
  const pinching = Math.sqrt(dx * dx + dy * dy) < 0.045;
  const pinchStarted = pinching && !cursor.classList.contains("pinch");
  const now = performance.now();
  cursor.classList.toggle("pinch", pinching);
  if (pinchStarted) {
    const target = findClickableElement(x, y);
    if (target) {
      target.click();
      showToast("Page control clicked.");
    }
  }

  const indexUp = landmarks[8].y < landmarks[6].y;
  const middleUp = landmarks[12].y < landmarks[10].y;
  const ringUp = landmarks[16].y < landmarks[14].y;
  const pinkyUp = landmarks[20].y < landmarks[18].y;
  if (now - lastScrollTime > 650) {
    if (indexUp && middleUp && !ringUp && !pinkyUp) {
      window.scrollBy({ top: -160, behavior: "smooth" });
      lastScrollTime = now;
    } else if (ringUp && pinkyUp && !indexUp && !middleUp) {
      window.scrollBy({ top: 160, behavior: "smooth" });
      lastScrollTime = now;
    }
  }
}

function trackHandFrame() {
  if (!trackingActive || !trackingVideo || !handTracker) return;
  if (trackingVideo.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && !inferencePending) {
    inferencePending = true;
    handTracker.send({ image: trackingVideo })
      .catch(() => {
        if (trackingActive) showToast("Hand tracking stopped unexpectedly. Turn gesture control off and try again.");
      })
      .finally(() => {
        inferencePending = false;
      });
  }
  if (trackingActive) requestAnimationFrame(trackHandFrame);
}

function loadHandTracker() {
  if (typeof window.Hands !== "function") {
    return Promise.reject(new Error("Hand tracking could not load. Check your internet connection, then refresh."));
  }
  const tracker = new window.Hands({
    locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`,
  });
  tracker.setOptions({
    maxNumHands: 1,
    modelComplexity: 1,
    minDetectionConfidence: 0.65,
    minTrackingConfidence: 0.65,
  });
  tracker.onResults(handleHandResults);
  return tracker.initialize().then(() => tracker);
}

async function startGestureControl() {
  if (!navigator.mediaDevices?.getUserMedia) {
    showToast("Camera access requires localhost or HTTPS and a supported browser.");
    setActivity("Camera access is not available", "Open Nexora on localhost or HTTPS, then allow camera access in your browser.");
    return;
  }

  gestureButton.disabled = true;
  gestureLabel.textContent = "Connecting camera…";
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
    handTracker = await loadHandTracker();
    if (!gestureButton.isConnected) {
      stopGestureControl();
      return;
    }
    trackingVideo = document.querySelector("#tracking-video");
    trackingVideo.autoplay = true;
    trackingVideo.muted = true;
    trackingVideo.playsInline = true;
    trackingVideo.srcObject = cameraStream;
    document.querySelector("#camera-float").classList.add("visible");
    await trackingVideo.play();
    trackingActive = true;
    setCameraStatus(true);
    gestureLabel.textContent = "Gesture control is on";
    gestureButton.setAttribute("aria-pressed", "true");
    gestureButton.disabled = false;
    document.body.classList.add("gesture-mode-active");
    requestAnimationFrame(trackHandFrame);
    setActivity("Gesture control is on", "Point with your index finger to move the page cursor. Pinch to click. Raise index and middle to scroll up; ring and pinky to scroll down.", true);
  } catch (error) {
    stopGestureControl();
    const message = error.name === "NotAllowedError"
      ? "Camera permission was denied. Allow camera access in your browser settings to use gesture control."
      : error.name === "NotFoundError"
        ? "No webcam was found. Connect a camera and try again."
        : error.message || "Could not start gesture control. Check the camera and try again.";
    showToast(message);
    setActivity("Could not connect the camera", message);
  } finally {
    gestureButton.disabled = false;
  }
}

gestureButton.addEventListener("click", () => {
  if (trackingActive) {
    stopGestureControl();
    setActivity("Gesture control paused", "The camera is off. Connect the webcam whenever you’re ready.");
  } else {
    startGestureControl();
  }
});
document.querySelector("#stop-camera").addEventListener("click", () => {
  stopGestureControl();
  setActivity("Gesture control paused", "The camera is off. Connect the webcam whenever you’re ready.");
});

function recognizeBrowserCommand(transcript) {
  const command = transcript.toLowerCase().replace(/[.!?]/g, "").trim();
  if (/\b(scroll down|page down)\b/.test(command)) {
    window.scrollBy({ top: Math.round(window.innerHeight * 0.7), behavior: "smooth" });
    return "Scrolled down the Nexora page.";
  }
  if (/\b(scroll up|page up)\b/.test(command)) {
    window.scrollBy({ top: -Math.round(window.innerHeight * 0.7), behavior: "smooth" });
    return "Scrolled up the Nexora page.";
  }
  if (/\b(overview|go home|go to the top|back to top)\b/.test(command)) {
    window.scrollTo({ top: 0, behavior: "smooth" });
    return "Returned to the Nexora overview.";
  }
  if (/\b(open gestures|gesture control|gestures)\b/.test(command)) {
    document.querySelector("#controls").scrollIntoView({ behavior: "smooth" });
    return "Showing the Nexora control modes.";
  }
  if (/\b(help|setup|desktop)\b/.test(command)) {
    openSetup();
    return "Opened desktop setup instructions.";
  }
  if (/\b(stop listening|stop voice)\b/.test(command)) {
    stopListening();
    return "Voice control stopped.";
  }
  if (/\b(click|left click)\b/.test(command)) {
    if (!trackingActive) return "For voice clicks, first enable gesture control. Desktop clicks need the companion.";
    const target = findClickableElement(Number.parseFloat(cursor.style.left), Number.parseFloat(cursor.style.top));
    if (target) {
      target.click();
      return "Clicked the page control under the gesture cursor.";
    }
    return "No page control is under the gesture cursor.";
  }
  return "Try “scroll down”, “scroll up”, “overview”, or “help”.";
}

function stopListening() {
  const wasListening = listening;
  listening = false;
  if (recognition && wasListening) recognition.stop();
  if (microphoneStream) {
    microphoneStream.getTracks().forEach((track) => track.stop());
    microphoneStream = null;
  }
  voiceButton.setAttribute("aria-pressed", "false");
  setMicStatus(false);
}

async function startListening() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    showToast("Speech recognition is not supported in this browser. Try the latest Chrome or Edge.");
    setActivity("Speech recognition is not supported", "Try this site in a current Chrome or Edge browser.");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    showToast("Microphone access requires localhost or HTTPS and a supported browser.");
    setActivity("Microphone access is not available", "Open Nexora on localhost or HTTPS, then allow microphone access.");
    return;
  }

  voiceButton.disabled = true;
  voiceLabel.textContent = "Connecting microphone…";
  try {
    microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    microphoneStream.getTracks().forEach((track) => track.stop());
    microphoneStream = null;

    recognition = new SpeechRecognition();
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => {
      listening = true;
      setMicStatus(true);
      voiceButton.setAttribute("aria-pressed", "true");
      setActivity("Listening for a voice command", "Say “scroll down”, “scroll up”, “overview”, or “help”. Commands control this page.", true);
    };
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript.trim();
      const result = recognizeBrowserCommand(transcript);
      showToast(`“${transcript}” — ${result}`);
      setActivity(`Heard: “${transcript}”`, result, true);
    };
    recognition.onerror = (event) => {
      const messages = {
        "not-allowed": "Microphone permission was denied. Allow it in your browser settings.",
        "audio-capture": "No microphone was found. Connect one and try again.",
        "network": "The browser speech service is unavailable. Check your internet connection.",
        "no-speech": "No speech was detected. Start listening and try a short command.",
      };
      const message = messages[event.error] || `Speech recognition error: ${event.error}.`;
      showToast(message);
      setActivity("Voice input needs attention", message);
    };
    recognition.onend = () => {
      listening = false;
      setMicStatus(false);
      voiceButton.setAttribute("aria-pressed", "false");
    };
    recognition.start();
  } catch (error) {
    if (microphoneStream) microphoneStream.getTracks().forEach((track) => track.stop());
    microphoneStream = null;
    const message = error.name === "NotAllowedError"
      ? "Microphone permission was denied. Allow it in your browser settings and try again."
      : error.name === "NotFoundError"
        ? "No microphone was found. Connect one and try again."
        : "Could not start voice control. Check microphone access and try again.";
    showToast(message);
    setActivity("Could not connect the microphone", message);
    setMicStatus(false);
  } finally {
    voiceButton.disabled = false;
    setMicStatus(listening);
  }
}

voiceButton.addEventListener("click", () => {
  if (listening) {
    stopListening();
    setActivity("Voice control paused", "The microphone is off. Start listening whenever you’re ready.");
  } else {
    startListening();
  }
});

document.querySelector("#copy-command").addEventListener("click", async () => {
  const command = ".\\venv\\Scripts\\python.exe .\\gesture_mouse.py";
  try {
    await navigator.clipboard.writeText(command);
    showToast("Desktop launch command copied.");
  } catch (error) {
    showToast(`Copy this command: ${command}`);
  }
});

window.addEventListener("pagehide", () => {
  stopGestureControl();
  stopListening();
});
