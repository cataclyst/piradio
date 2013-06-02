import mpd
import gaugette.rotary_encoder
import gaugette.switch
import gaugette.rgbled
import threading
import time
import math
import sys

# Pins used by the rotary encoder
ROT_A_PIN = 5
ROT_B_PIN = 4

# Pin used by the push button
BUTTON_PIN = 8

# Pins used by the LEDs
R_LED_PIN = 2
G_LED_PIN = 0
B_LED_PIN = 1

# Colors (in red, green, blue) to use for the modes
COLOR_VOLUME = [100,   0,   0]
COLOR_TRACKS = [0,   100,   0]
COLOR_OFF    = [0,     0,   0]

# Initial volume in percent
INITIAL_VOLUME = 80

# Factor in percent to add to the volume for a delta of 1:
VOLUME_FACTOR = 0.2

# Duration to interpret as a "long" button press (in ms)
LONG_PRESS_DURATION = 1200

# Amount to turn the rotator before a track/station is changed:
TRACK_ROTATION_THRESHOLD = 20

# Set to True to enable some debug output:
DEBUG = False

class PiRadio:
  
  def __init__(self):
  
    # Mode distincts between 'VOLUME', 'TRACKS' and 'OFF'
    self.mode = "VOLUME"
    
    # MPD client connection for playback
    self.playback = mpd.MPDClient()
    
    # Convenience and performance improvement: store the last volume
    self.last_volume = INITIAL_VOLUME
    
    # Remember a rotation value for changing the track:
    self.last_track_rotation = 0
    
    # Initialize and start the playback:
    self.playback.timeout = 10
    self.playback.idletimeout = None
    self.playback.connect("localhost", 6600)
    self.playback.setvol(self.last_volume)
    self.playback.play()
    
    # Start the thread that listens for changes to the rotary encoder:
    rotator_thread = RotatorThread(self)
    rotator_thread.start()
    
    # Start the thread that listens for button pushes:
    button_thread = ButtonThread(self)
    button_thread.start()
    
    # LED for indicating the mode
    self.led = gaugette.rgbled.RgbLed(R_LED_PIN, G_LED_PIN, B_LED_PIN)
    
    self.adapt_led()
    
    try:
      while True:
        time.sleep(10)
    except KeyboardInterrupt:
      print("Shutting down threads")
      rotator_thread.stop()
      button_thread.stop()
      print("Threads shut down")
    except:
      rotator_thread.stop()
      button_thread.stop()
      raise
    
  def rotator_changed(self, delta):
    # Depending on the current mode, do something:
    
    # If in "change volume" mode, add a certain factor of the delta to the volume:
    if self.mode == "VOLUME":
      self.last_volume += (delta * VOLUME_FACTOR)
      # Clamp the volume between 0 and 100:
      self.last_volume = min(100, max(0, self.last_volume))
      if DEBUG:
        print("Volume: %3.1f" % self.last_volume)
      self.playback.setvol(int(self.last_volume))
      
    # If in "change tracks" mode, count rotations until a change of track is reached:
    elif self.mode == "TRACKS":
      self.last_track_rotation += delta
      if DEBUG:
        print("Last track rotation: %d" % self.last_track_rotation)
      if abs(self.last_track_rotation) > TRACK_ROTATION_THRESHOLD:
        if math.copysign(1, self.last_track_rotation) < 0:
          if DEBUG:
            print("Going back to previous track")
          self.playback.previous()
        else:
          if DEBUG:
            print("Advancing to next track")
          self.playback.next()
        self.last_track_rotation = 0

  def button_released(self):
    # Depending on the current mode, react to the button release:
    if DEBUG:
      print("Button released")
    if self.mode == "VOLUME":
      self.mode = "TRACKS"
      if DEBUG:
        print("Mode changed to 'TRACKS'")
    else:
      self.mode = "VOLUME"
      if DEBUG:
        print("Mode changed to 'VOLUME'")
    self.adapt_led()
    
  def button_long_press(self):
    # Depending on the current mode, a long press on the button turns playback off or on:
    if self.mode == "OFF":
      if DEBUG:
        print("Mode changed to 'VOLUME' (turning back on)")
      self.mode = "VOLUME"
      self.playback.play()
    else:
      self.mode = "OFF"
      if DEBUG:
        print("Mode changed to 'OFF'")
      self.playback.stop()
    self.adapt_led()
    
  def adapt_led(self):
    if self.mode == "VOLUME":
      colors = COLOR_VOLUME
    elif self.mode == "TRACKS":
      colors = COLOR_TRACKS
    elif self.mode == "OFF":
      colors = COLOR_OFF
      
    if self.mode == "OFF":
      f = self.led.set
    else:
      f = self.led.fade
    f(colors[0], colors[1], colors[2])
    
class RotatorThread(threading.Thread): 
  def __init__(self, pi_radio): 
    threading.Thread.__init__(self)
    
    # Store the PiRadio instance that we are gonna report rotation changes back on:
    self.master = pi_radio
    
    # Rotary encoder for changing volume or tracks
    self.rotator = gaugette.rotary_encoder.RotaryEncoder(ROT_A_PIN, ROT_B_PIN)
    
    # Indicator for the thread to finish:
    self.stop_requested = False

  def stop(self):
    self.stop_requested = True

  def run(self):
    while not self.stop_requested:
      delta = self.rotator.get_delta()
      if delta != 0:
        self.master.rotator_changed(delta)
      time.sleep(0.01)
    if DEBUG:
      print("RotatorThread stopped")
      
class ButtonThread(threading.Thread): 
  def __init__(self, pi_radio): 
    threading.Thread.__init__(self)
    
    # Store the PiRadio instance that we are gonna report button pushes back on:
    self.master = pi_radio
    
    # Push button to change between modes and to stop and start playback
    self.switch = gaugette.switch.Switch(BUTTON_PIN)
    
    # Indicator for the thread to finish:
    self.stop_requested = False

  def stop(self):
    self.stop_requested = True

  def run(self):
    last_state = False
    # Used to indicate that a long-press should not be additionally 
    # considered a button release:
    long_press_registered = False
    time_of_press = -1
    while not self.stop_requested:
      sw_state = self.switch.get_state()
      if sw_state != last_state:
        # Check if the button has just been released:
        if sw_state == 0:
          time_of_press = -1
          # Only process this release if it has not already been processed as a long press:
          if not long_press_registered:
            self.master.button_released()
          else:
            long_press_registered = False
        else:
          # If the button has just been pressed down, start counting the time it has been pressed:
          time_of_press = time.time()
        last_state = sw_state
      elif sw_state == 1:
        if DEBUG and time_of_press > 0:
          print ((time.time() - time_of_press)) * 1000
        # Check if the button has been pressed long enough to trigger a long-press event:
        if (time_of_press > 0) and ((time.time() - time_of_press) * 1000 > LONG_PRESS_DURATION):
          self.master.button_long_press()
          long_press_registered = True
          time_of_press = -1
      time.sleep(0.01)
    if DEBUG:
      print("ButtonThread stopped")
      
if __name__ == "__main__":
  if len(sys.argv) == 2 and sys.argv[1].lower() == "debug":
    DEBUG = True
  if DEBUG:
    print("Starting PiRadio...")
  PiRadio()
  if DEBUG:
    print("PiRadio finished")
  
  
  