
import cv2
import mediapipe as mp
import pyautogui
import speech_recognition as sr
import pyttsx3
import pygetwindow as gw

import os
import queue
import threading
import time
import webbrowser
import subprocess
from datetime import datetime
from urllib.parse import quote_plus


# =========================================================
# CONFIGURATION
# =========================================================

WINDOW_TITLE = "Real Time Gesture Mouse with Voice Assistant"

FRAME_W = 640
FRAME_H = 480

# Lower values make cursor movement smoother.
SMOOTHING = 5

# Gesture detection thresholds in normalized landmark coordinates.
PINCH_THRESHOLD = 0.045
CLICK_COOLDOWN = 0.5
DRAG_HOLD_SECONDS = 0.45

SCREEN_W, SCREEN_H = pyautogui.size()

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

command_queue = queue.Queue()
speech_queue = queue.Queue()

mouse_enabled = True
running = True

# Gesture state
prev_x, prev_y = 0, 0
last_click_time = 0
pinch_start_time = None
dragging = False
right_click_latched = False
scroll_last_time = 0

# Webcam and MediaPipe
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.65,
    min_tracking_confidence=0.65
)


# =========================================================
# SPEECH OUTPUT
# =========================================================

def speak(message):
    """Queue a message for the speech-output thread."""
    speech_queue.put(str(message))


def speech_worker():
    """Keep text-to-speech separate from mouse and camera processing."""
    engine = pyttsx3.init()
    engine.setProperty("rate", 175)

    while True:
        message = speech_queue.get()

        if message is None:
            break

        try:
            print("Assistant:", message)
            engine.say(message)
            engine.runAndWait()
        except Exception as error:
            print("Speech error:", error)

    engine.stop()


threading.Thread(target=speech_worker, daemon=True).start()


# =========================================================
# VOICE INPUT
# =========================================================

recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = True


def voice_callback(recognizer_instance, audio):
    """Runs in the background when microphone audio is detected."""
    try:
        command = recognizer_instance.recognize_google(audio)
        command = command.lower().strip()

        if command:
            print("You said:", command)
            command_queue.put(command)

    except sr.UnknownValueError:
        pass

    except sr.RequestError:
        command_queue.put("__speech_service_error__")


# =========================================================
# WINDOW MANAGEMENT
# =========================================================

def close_active_window():
    """Close the active window without force-killing its process."""
    try:
        window = gw.getActiveWindow()

        if window is None:
            speak("No active window found.")
            return

        title = (window.title or "").strip()

        # Protect the webcam window from accidental closure.
        if WINDOW_TITLE.lower() in title.lower():
            speak("I cannot close the camera window using this command.")
            return

        if not title:
            speak("I cannot identify the active window.")
            return

        window.close()
        speak("Close request sent for " + title)

    except Exception as error:
        print("Window closing error:", error)
        speak("Unable to close this window.")


def close_named_window(name):
    """Close a window whose title contains the requested application name."""
    try:
        matches = gw.getWindowsWithTitle(name)

        matches = [
            window for window in matches
            if window.title and WINDOW_TITLE.lower() not in window.title.lower()
        ]

        if not matches:
            speak("I could not find " + name)
            return

        matches[0].close()
        speak("Close request sent for " + name)

    except Exception as error:
        print("Named window closing error:", error)
        speak("Unable to close " + name)


# =========================================================
# OPEN APPLICATIONS AND WEBSITES
# =========================================================

def open_application(name):
    """Open common Windows applications."""
    try:
        if name == "notepad":
            subprocess.Popen(["notepad.exe"])

        elif name == "calculator":
            subprocess.Popen(["calc.exe"])

        elif name == "chrome":
            # Opens Chrome if it is installed and available in PATH.
            subprocess.Popen(["cmd", "/c", "start", "", "chrome"])

        elif name == "google":
            webbrowser.open("https://www.google.com")

        elif name == "youtube":
            webbrowser.open("https://www.youtube.com")

        elif name == "gmail":
            webbrowser.open("https://mail.google.com")

        else:
            speak("I do not know how to open " + name)
            return

        speak("Opening " + name)

    except Exception as error:
        print("Open application error:", error)
        speak("Unable to open " + name)


# =========================================================
# VOICE-CONTROLLED MOUSE ACTIONS
# =========================================================

def voice_mouse_action(command):
    """Return True if the command was handled here."""
    global mouse_enabled

    # Voice-only mode avoids the hand tracker overriding
    # cursor movements requested by voice.
    if command in ("voice mouse mode", "enable voice mouse"):
        mouse_enabled = False
        speak("Voice mouse mode enabled.")
        return True

    if command in ("gesture mouse mode", "enable gesture mouse"):
        mouse_enabled = True
        speak("Gesture mouse mode enabled.")
        return True

    # Move the cursor by a fixed distance.
    movements = {
        "move mouse left": (-100, 0),
        "move mouse right": (100, 0),
        "move mouse up": (0, -100),
        "move mouse down": (0, 100),
        "move cursor left": (-100, 0),
        "move cursor right": (100, 0),
        "move cursor up": (0, -100),
        "move cursor down": (0, 100)
    }

    if command in movements:
        mouse_enabled = False
        dx, dy = movements[command]
        pyautogui.moveRel(dx, dy, duration=0.2)
        speak("Moved.")
        return True

    if command in ("left click", "click", "single click"):
        pyautogui.click(button="left")
        speak("Left click.")
        return True

    if command in ("double click", "double-click"):
        pyautogui.doubleClick()
        speak("Double click.")
        return True

    if command in ("right click", "right-click"):
        pyautogui.click(button="right")
        speak("Right click.")
        return True

    if command in ("scroll up", "page up"):
        pyautogui.scroll(5)
        speak("Scrolling up.")
        return True

    if command in ("scroll down", "page down"):
        pyautogui.scroll(-5)
        speak("Scrolling down.")
        return True

    if command in ("drag start", "start dragging", "hold mouse"):
        pyautogui.mouseDown(button="left")
        speak("Dragging started.")
        return True

    if command in ("drag stop", "stop dragging", "release mouse"):
        pyautogui.mouseUp(button="left")
        speak("Mouse released.")
        return True

    return False


# =========================================================
# VOICE COMMAND PROCESSING
# =========================================================

def process_voice_command(command):
    global mouse_enabled, running, dragging, pinch_start_time

    command = command.lower().strip()

    if command == "__speech_service_error__":
        speak("The speech service is unavailable. Check your internet connection.")
        return

    # Exit commands
    if command in (
        "exit assistant",
        "stop assistant",
        "quit assistant",
        "exit program"
    ):
        speak("Stopping the assistant.")
        running = False
        return

    # Help
    if command in ("help", "voice commands", "what can you do"):
        speak(
            "You can move the mouse, click, double click, right click, "
            "scroll, drag, open applications, close windows, search the web, "
            "take screenshots, and pause or resume gesture control."
        )
        print("""
VOICE COMMANDS
--------------
Mouse:
  Move mouse left
  Move mouse right
  Move mouse up
  Move mouse down
  Left click
  Double click
  Right click
  Scroll up
  Scroll down
  Drag start
  Drag stop

Modes:
  Voice mouse mode
  Gesture mouse mode
  Pause mouse
  Resume mouse

Applications:
  Open Notepad
  Open Calculator
  Open Chrome
  Open Google
  Open YouTube
  Open Gmail

Windows:
  Close window
  Close Notepad
  Close Chrome
  Close Calculator

Other:
  Search for Python tutorials
  What time is it
  What is today's date
  Take screenshot
  Help
  Stop assistant
""")
        return

    # Voice-controlled mouse actions
    if voice_mouse_action(command):
        return

    # Pause and resume gesture control
    if command in ("pause mouse", "pause gesture", "disable mouse"):
        mouse_enabled = False
        speak("Gesture mouse paused.")
        return

    if command in ("resume mouse", "resume gesture", "enable mouse"):
        mouse_enabled = True
        speak("Gesture mouse resumed.")
        return

    # Open applications
    if command.startswith("open "):
        target = command[5:].strip()

        if target in ("notepad", "calculator", "chrome", "google",
                      "youtube", "gmail"):
            open_application(target)
        elif target in ("browser", "internet", "web browser"):
            open_application("chrome")
        else:
            speak("Application not recognized.")
        return

    # Close the active window
    if command in (
        "close window",
        "close current window",
        "close this window",
        "close active window",
        "close application",
        "close app"
    ):
        close_active_window()
        return

    # Close a named application window
    for app_name in ("notepad", "chrome", "calculator"):
        if command in (
            "close " + app_name,
            "close " + app_name + " window"
        ):
            close_named_window(app_name)
            return

    # Websites and searches
    if command in ("open youtube", "open gmail", "open google"):
        return

    if command.startswith("search for "):
        query = command[len("search for "):].strip()
        if query:
            webbrowser.open(
                "https://www.google.com/search?q=" + quote_plus(query)
            )
            speak("Searching for " + query)
        return

    if command.startswith("search "):
        query = command[len("search "):].strip()
        if query:
            webbrowser.open(
                "https://www.google.com/search?q=" + quote_plus(query)
            )
            speak("Searching for " + query)
        return

    # Time and date
    if "time" in command and (
        "what" in command or "tell" in command
    ):
        current_time = datetime.now().strftime("%I:%M %p")
        speak("The time is " + current_time)
        return

    if "date" in command and (
        "what" in command or "today" in command
    ):
        current_date = datetime.now().strftime("%d %B %Y")
        speak("Today's date is " + current_date)
        return

    # Screenshot
    if command in ("take screenshot", "screenshot", "capture screen"):
        try:
            os.makedirs("screenshots", exist_ok=True)
            filename = datetime.now().strftime(
                "screenshots/screenshot_%Y%m%d_%H%M%S.png"
            )
            pyautogui.screenshot().save(filename)
            speak("Screenshot saved.")
            print("Screenshot saved at:", os.path.abspath(filename))
        except Exception as error:
            print("Screenshot error:", error)
            speak("Could not take the screenshot.")
        return

    speak("Command not recognized. Say help for available commands.")


# =========================================================
# HAND GESTURE CONTROL
# =========================================================

def landmark_distance(point_a, point_b):
    dx = point_a.x - point_b.x
    dy = point_a.y - point_b.y
    return (dx * dx + dy * dy) ** 0.5


def process_hand_gesture(hand_landmarks):
    global prev_x, prev_y
    global last_click_time, pinch_start_time
    global dragging, right_click_latched, scroll_last_time

    landmarks = hand_landmarks.landmark

    thumb_tip = landmarks[4]
    index_tip = landmarks[8]
    middle_tip = landmarks[12]
    ring_tip = landmarks[16]
    pinky_tip = landmarks[20]

    # Move cursor using the index finger.
    target_x = int(index_tip.x * SCREEN_W)
    target_y = int(index_tip.y * SCREEN_H)

    # Smooth movement.
    smooth_x = prev_x + (target_x - prev_x) / SMOOTHING
    smooth_y = prev_y + (target_y - prev_y) / SMOOTHING

    smooth_x = max(1, min(SCREEN_W - 2, int(smooth_x)))
    smooth_y = max(1, min(SCREEN_H - 2, int(smooth_y)))

    if mouse_enabled:
        pyautogui.moveTo(smooth_x, smooth_y)

    prev_x, prev_y = smooth_x, smooth_y

    # Thumb and index finger pinch: click or drag.
    thumb_index_distance = landmark_distance(thumb_tip, index_tip)
    now = time.time()

    if thumb_index_distance < PINCH_THRESHOLD:
        if pinch_start_time is None:
            pinch_start_time = now

        held_time = now - pinch_start_time

        if (
            held_time >= DRAG_HOLD_SECONDS
            and not dragging
            and mouse_enabled
        ):
            pyautogui.mouseDown(button="left")
            dragging = True

    else:
        if dragging:
            if mouse_enabled:
                pyautogui.mouseUp(button="left")
            dragging = False
            pinch_start_time = None

        elif (
            pinch_start_time is not None
            and now - pinch_start_time < DRAG_HOLD_SECONDS
            and now - last_click_time > CLICK_COOLDOWN
            and mouse_enabled
        ):
            pyautogui.click(button="left")
            last_click_time = now

        pinch_start_time = None

    # Thumb and middle finger pinch: right click.
    thumb_middle_distance = landmark_distance(thumb_tip, middle_tip)

    if thumb_middle_distance < PINCH_THRESHOLD:
        if not right_click_latched and mouse_enabled:
            pyautogui.click(button="right")
            right_click_latched = True
    else:
        right_click_latched = False

    # Index + middle raised, ring + pinky folded: scroll up.
    # Ring + pinky raised, index + middle folded: scroll down.
    index_up = landmarks[8].y < landmarks[6].y
    middle_up = landmarks[12].y < landmarks[10].y
    ring_up = landmarks[16].y < landmarks[14].y
    pinky_up = landmarks[20].y < landmarks[18].y

    if mouse_enabled and now - scroll_last_time > 0.25:
        if index_up and middle_up and not ring_up and not pinky_up:
            pyautogui.scroll(2)
            scroll_last_time = now

        elif ring_up and pinky_up and not index_up and not middle_up:
            pyautogui.scroll(-2)
            scroll_last_time = now


# =========================================================
# MAIN PROGRAM
# =========================================================

def main():
    global running, dragging

    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        print("ERROR: Could not open webcam.")
        speak("Could not open the webcam.")
        return

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

    # Start microphone listener in the background.
    microphone = None
    stop_listening = None

    try:
        microphone = sr.Microphone()

        with microphone as source:
            print("Calibrating microphone. Please wait...")
            recognizer.adjust_for_ambient_noise(source, duration=1)

        stop_listening = recognizer.listen_in_background(
            microphone,
            voice_callback,
            phrase_time_limit=5
        )

        print("Voice assistant started.")
        speak("Voice assistant ready. Say help to hear the commands.")

    except Exception as error:
        print("Microphone initialization error:", error)
        print("Gesture control will continue without voice input.")
        speak("Microphone unavailable. Gesture control is still active.")

    cv2.namedWindow(WINDOW_TITLE)

    try:
        while running:
            success, frame = camera.read()

            if not success:
                print("Could not read a webcam frame.")
                break

            frame = cv2.flip(frame, 1)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = hands.process(rgb_frame)

            # Handle voice commands without blocking the camera loop.
            while not command_queue.empty():
                try:
                    command = command_queue.get_nowait()
                    process_voice_command(command)
                except queue.Empty:
                    break

            if result.multi_hand_landmarks:
                for hand_landmarks in result.multi_hand_landmarks:
                    mp_draw.draw_landmarks(
                        frame,
                        hand_landmarks,
                        mp_hands.HAND_CONNECTIONS
                    )

                    if mouse_enabled:
                        process_hand_gesture(hand_landmarks)

            # Status overlay.
            status = "GESTURE MODE" if mouse_enabled else "VOICE MODE"
            cv2.putText(
                frame,
                status,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                "Press ESC to exit | Say 'help' for commands",
                (10, FRAME_H - 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (255, 255, 255),
                1
            )

            cv2.imshow(WINDOW_TITLE, frame)

            # ESC closes the assistant.
            if cv2.waitKey(1) & 0xFF == 27:
                running = False

    except pyautogui.FailSafeException:
        print("PyAutoGUI safety stop activated.")
        speak("Mouse safety stop activated.")

    except Exception as error:
        print("Main program error:", error)
        speak("An error occurred. Stopping the assistant.")

    finally:
        # Release a held mouse button if the program exits during a drag.
        try:
            pyautogui.mouseUp(button="left")
        except Exception:
            pass

        if stop_listening is not None:
            stop_listening(wait_for_stop=False)

        camera.release()
        cv2.destroyAllWindows()
        hands.close()

        # Let queued speech finish before stopping the speech worker.
        speech_queue.put(None)

        print("Assistant stopped.")


if __name__ == "__main__":
    main()
