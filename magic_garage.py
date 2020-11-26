#!/home/patrick/src/Magic-Garage/.env/bin/python3
import json
import sys
import configparser
import requests
import time
import pytz
import os
import threading
import logging
from os.path import getsize
from datetime import datetime
from geopy import distance, location

# Home location GPS Coordinates
HOME_LOCATION = location.Point(33.812671, -117.920392)
# App Constants
LOG_FILE_NAME = "debug.log"
DEBUG_LOG_MAX_SIZE_BYTES = 5000000
TESLA_TOKEN_EXPIRE_CHECK_SECS = 24 * 60 * 60
TESLA_LOCATION_DELAY_SECS = 2
TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_FAST = 1
TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_SLOW = 5 * 60
TESLA_STALE_DATA_THRESHOLD_SECS = 2 * TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_SLOW
TESLA_PULL_OUT_GARAGE_DELAY_SECS = 3
HOME_GEO_FENCE_FT = 20
AWAY_GEO_FENCE_FT = 2000
FAR_AWAY_GEO_FENCE_FT = 26400
ARRIVING_GEO_FENCE_FT = 1500
OPEN_DOOR_GEO_FENCE_FT = 500
MYQ_DOOR_STATE_POLL_INTERVAL_SECS = 2
MYQ_DOOR_STATE_POLL_TIMEOUT_SECS = 30
MYQ_DOOR_STATE_CHECK_SECS = 60
WATCHDOG_TIMEOUT_SECS = 5 * 60
WATCHDOG_RESET_SECS = 60
watch_dog_last_update = time.time()

# Tesla Configs (Original API Reference from Tim Dorr: https://tesla-api.timdorr.com/)
TESLA_CLIENT_ID = "81527cff06843c8634fdc09e8ac0abefb46ac849f38fe1e431c2ef2106796384"
TESLA_CLIENT_SECRET = "c7257eb71a564034f9419ee651c7d0e5f7aa6bfbd18bafb5c5c033b093bb2fa3"
TESLA_BASE_API_URL = "https://owner-api.teslamotors.com"
TESLA_AQUIRE_TOKEN = "/oauth/token?grant_type=password"
TESLA_REFRESH_TOKEN = "/oauth/token?grant_type=refresh_token"
TESLA_VEHICLES = "/api/1/vehicles"
TESLA_VEHICLE_DATA = "/api/1/vehicles/{id}/vehicle_data"
TESLA_VEHICLE_STATE = "/api/1/vehicles/{id}/data_request/vehicle_state"
TESLA_DRIVE_STATE = "/api/1/vehicles/{id}/data_request/drive_state"

# MyQ Configs (Original Reference from Jordan Chanomie: https://github.com/chanomie/homebridge-myq/blob/025b7a1cb4a6cf0cc0a37506b1f87ecae7c71996/README.md)
MYQ_BASE_API_URL = "https://api.myqdevice.com"
MYQ_LOCALE = "en"
MYQ_LOGIN = "/api/v5/Login"
MYQ_ACCOUNT_ID = "/api/v5/My?expand=account"
MYQ_DEVICE_LIST = "/api/v5.1/Accounts/{account_id}/Devices"
MYQ_DEVICE_SET = "/api/v5.1/Accounts/{account_id}/Devices/{device_id}/actions"
MYQ_APP_ID = "Vj8pQggXLhLy0WHahglCD4N1nAkkXQtGYpq2HrHD7H1nvmbT55KqtN6RSF4ILB/i"

# Tesla Global Variables
tesla_email = ""
tesla_password = ""
tesla_auth_token = ""
tesla_refresh_token = ""
tesla_token_timeout = ""
tesla_token_start_time = time.time()
tesla_last_data_update = time.time()
tesla_auth_header = {}
tesla_vehicle_ids = []
distance_from_home = 0.0
tesla_shift_state = "PARKED"
tesla_last_set_interval = 0
tesla_charger_connected = False
tesla_driver_present = False
tesla_awake = True
tests_speed = 0
tesla_vehicle_thread_sleep = TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_FAST
vehicle_thread_interval_changed = False

# MyQ Variables
myq_email = ""
myq_password = ""
myq_auth_token = ""
myq_auth_header = {}
myq_account_id = ""
myq_device_id = ""
myq_door_state = ""
myq_last_set_interval  = 0
myq_door_thread_sleep = MYQ_DOOR_STATE_CHECK_SECS
myq_door_thread_interval_changed = False

# General Functions
# Initialize debug logging
def logging_init():
    logging.basicConfig(filename=LOG_FILE_NAME, filemode='a', level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%d-%b-%y %I:%M:%S%p')

# Clears the logfile it it gets too large
def check_log_file_size():
    if (getsize(LOG_FILE_NAME) > DEBUG_LOG_MAX_SIZE_BYTES):
        os.remove(LOG_FILE_NAME)
        logging.info("***** Debug Log Cleared *****")

# Logs any catastrophic error and terminates the script
def print_error_and_exit(message):
    logging.error(message)
    exit()

# Watchdog timer to kill the app in case it goes off the rails
def watchdog():
    global watch_dog_last_update

    while (True):
        if ((time.time() - watch_dog_last_update) >= WATCHDOG_TIMEOUT_SECS):
            print_error_and_exit("Watchdog Timer Expired")
        else:
            watch_dog_last_update = time.time()
        time.sleep(WATCHDOG_RESET_SECS)

# Parses Tesla and MyQ credentials from the command line parameters
def parse_input_parameters():
    global tesla_email
    global tesla_password
    global myq_email
    global myq_password

    try:
        tesla_email = sys.argv[1]
        tesla_password = sys.argv[2]
        myq_email = sys.argv[3]
        myq_password = sys.argv[4]
        if ((len(tesla_email) < 1) or (len(tesla_password) < 1) or 
            (len(myq_email) < 1) or (len(myq_password) < 1)):
            print_error_and_exit("Incorrect input parameters")
    except IndexError:
        print_error_and_exit("Incorrect input parameters")

# Tesla Functions
# Gets a Tesla Auth Token
def tesla_login(email, password):
    global tesla_auth_token
    global tesla_refresh_token
    global tesla_auth_header
    global tesla_refresh_token
    global tesla_token_timeout
    global tesla_token_start_time

    body = {
        "grant_type": "password",
        "client_id": TESLA_CLIENT_ID,
        "client_secret": TESLA_CLIENT_SECRET,
        "email": email,
        "password": password
    }
    try:
        logging.info("Getting Tesla Auth Token")
        response = requests.post(TESLA_BASE_API_URL + TESLA_AQUIRE_TOKEN, None, json=body, timeout=3)
        resp = json.loads(response.text)
        tesla_auth_token = resp["access_token"]
        tesla_refresh_token = resp["refresh_token"]
        tesla_token_timeout = resp["expires_in"]
        tesla_auth_header = {
            "Authorization": "Bearer " + tesla_auth_token,
            "Content-Type": "application/json"
        }
        logging.info("Tesla Auth Token Aquired")
        tesla_token_start_time = time.time()
    except Exception as e:
        print(e)
        print_error_and_exit("Failed to get Tesla Auth Token " + str(response))

# Refreshes the Tesla Auth Token
def tesla_refresh_auth_token():
    global tesla_auth_token
    global tesla_refresh_token
    global tesla_auth_header
    global tesla_refresh_token
    global tesla_token_timeout
    global tesla_token_start_time

    body = {
        "grant_type": "refresh_token",
        "client_id": TESLA_CLIENT_ID,
        "client_secret": TESLA_CLIENT_SECRET,
        "refresh_token": tesla_refresh_token
    }
    try:
        logging.info("Refreshing Tesla Auth Token")
        response = requests.post(TESLA_BASE_API_URL + TESLA_REFRESH_TOKEN, None, json=body)
        resp = json.loads(response.text)
        tesla_auth_token = resp["access_token"]
        tesla_refresh_token = resp["refresh_token"]
        tesla_token_timeout = resp["expires_in"]
        tesla_auth_header = {
            "Authorization": "Bearer " + tesla_auth_token,
            "Content-Type": "application/json"
        }
        logging.info("Successfully Refreshed Tesla Auth Token")
        tesla_token_start_time = time.time()
    except:
        logging.error("Failed to Refresh Tesla Auth Token: " + str(response.status_code))

# Checks if the Tesla Auth Token is about to expire and refreshes it if needed
def tesla_check_token_expired():
    while (True):
        now = time.time()
        elapsed = now - tesla_token_start_time
        # Refresh if the token will expire within a day
        if ((tesla_token_timeout - elapsed) <= 24 * 60 * 60):
            tesla_refresh_auth_token()
        time.sleep(TESLA_TOKEN_EXPIRE_CHECK_SECS)

# Gets all the vehicle IDs for the account
def tesla_get_vehicles():
    global tesla_vehicle_ids

    try:
        logging.info("Getting Tesla Vehicles...")
        response = requests.get(TESLA_BASE_API_URL + TESLA_VEHICLES, headers=tesla_auth_header)
        resp = json.loads(response.text)
        for vehicle in resp['response']:
            tesla_vehicle_ids.append(vehicle["id"])
        logging.info("Successfully Acquired Tesla Vehicle IDs")
    except:
        print_error_and_exit("Failed to get Tesla Vehicle IDs: " + str(response.status_code))

# Gets data indicating whether the charger is connected to the car
def tesla_get_charger_connected():
    global tesla_charger_connected

    # Since this call returns an error fairly often, default to Disconnected in those cases so the logic to detect
    # when the car leaves has a better chance of working
    tesla_charger_connected = False
    try:
        url = TESLA_BASE_API_URL + TESLA_VEHICLE_DATA
        #NOTE: Currently only works with a single vehicle ID
        for id in tesla_vehicle_ids:
            response = requests.get(url.replace("{id}", str(id)), headers=tesla_auth_header)
            if (response.status_code == 200):
                resp = json.loads(response.text)
                if(tesla_is_vehicle_available(resp)):
                    if ("Disconnected" not in resp['response']['charge_state']['charging_state']):
                        tesla_charger_connected = True
            else:
                if (response.status_code != 408):
                    logging.error("Failed to get Tesla Charging State: " + str(response.status_code))
    except:
        logging.info("Failed to get Tesla Charging State: " + str(response.status_code))

# Gets data indicating whether the driver is present
def tesla_get_driver_present():
    global tesla_driver_present

    try:
        url = TESLA_BASE_API_URL + TESLA_VEHICLE_STATE
        #NOTE: Currently only works with a single vehicle ID
        for id in tesla_vehicle_ids:
            response = requests.get(url.replace("{id}", str(id)), headers=tesla_auth_header)
            if (response.status_code == 200):
                resp = json.loads(response.text)
                if(tesla_is_vehicle_available(resp)):
                    tesla_driver_present = resp['response']['is_user_present']
            else:
                if (response.status_code != 408):
                    logging.error("Failed to get Tesla Driver State: " + str(response.status_code))
    except:
        logging.error("Failed to get Tesla Driver State: " + str(response.status_code))

# Gets drive data and logs it, including previously fetched charger and driver states
def tesla_get_drive_state():
    global tesla_awake
    global tests_speed
    global tesla_shift_state
    global tesla_last_data_update

    try:
        url = TESLA_BASE_API_URL + TESLA_DRIVE_STATE
        #NOTE: Currenlty only works with a single vehicle ID
        for id in tesla_vehicle_ids:
            response = requests.get(url.replace("{id}", str(id)), headers=tesla_auth_header)
            resp = json.loads(response.text)
            if (tesla_is_vehicle_available(resp) and response.status_code == 200):
                tesla_latitude = 0.0
                tesla_longitude = 0.0
                tesla_speed = 0
                tesla_awake = True
                if (resp['response']['speed']):
                    tesla_speed = resp['response']['speed']
                tesla_shift_state = shift_state(resp['response']['shift_state'])
                tesla_latitude = resp['response']['latitude']
                tesla_longitude = resp['response']['longitude']
                calculate_current_distance_from_home_feet(tesla_latitude, tesla_longitude)
                relative_location = tesla_get_relative_location()
                    
                charger = "Disconnected"
                if (tesla_charger_connected):
                    charger = "Connected"
                driver_present = "NO"
                if (tesla_driver_present):
                    driver_present = "YES"

                logging.info("Tesla State: " + tesla_shift_state + " | Driver Present: " + driver_present + " | " + "Charger: " + charger + " | Speed: "
                    + str(tesla_speed) + "MPH | " + " Location: " + relative_location + " | " + str(distance_from_home) + "FT from Home")
            else:
                if (response.status_code == 408):
                    logging.info("Unable to get drive state. Car is likely asleep")
                    tesla_awake = False
                else:
                    logging.error("Failed to get Tesla Drive State: " + str(response.status_code))
            tesla_last_data_update = time.time()
    except Exception as e:
        print(e)
        logging.exception("Failed to get Tesla Drive State: " + str(e))

# If the app gets into a state where new data is not being captured, force a restart
def tesla_check_for_stale_data():
    if ((time.time() - tesla_last_data_update) > TESLA_STALE_DATA_THRESHOLD_SECS):
        print_error_and_exit("Stale data detected that is older than " + str(TESLA_STALE_DATA_THRESHOLD_SECS)
            + " seconds. Exiting...")

# Determines whether the response from Tesla indicates the data is unavailable
def tesla_is_vehicle_available(message):
    return not ("vehicle unavailable" in message)

# Determines if the data fetch interval should decrease
def tesla_check_if_fetch_interval_should_change_to_slow():
    # Car is asleep, far away, or at home with no driver, slow vehicle data interval to prevent keeping the car awake
    return ((not tesla_awake) or tesla_is_far_away() or (tesla_is_vehicle_home() and not tesla_driver_present))

# Determines if the data fetch interval should increase
def tesla_check_if_fetch_interval_should_change_to_fast():
    # Car is driver is present and the car is nearby or the door is open
    return ((tesla_driver_present and not tesla_is_far_away()) or myq_door_open())

# Returns the distance in feet the GPS coordinates are from Home
def calculate_current_distance_from_home_feet(latitude, longitude):
    global distance_from_home
    if ((latitude == 0.0) or (longitude == 0.0)):
        print_error_and_exit("Tesla Location Data Invalid")
    tesla_location = (latitude, longitude)
    distance_from_home = round(distance.distance(HOME_LOCATION, tesla_location).feet, 2)

# Returns relative distance from home - HOME
def tesla_is_vehicle_home():
    return (distance_from_home <= HOME_GEO_FENCE_FT)

# Returns relative distance from home - NEARBY
def tesla_is_vehicle_nearby():
    return (distance_from_home >= HOME_GEO_FENCE_FT) and (distance_from_home <= AWAY_GEO_FENCE_FT)

# Returns relative distance from home - AWAY
def tesla_is_vehicle_away():
    return (distance_from_home >= AWAY_GEO_FENCE_FT) and (distance_from_home <= FAR_AWAY_GEO_FENCE_FT)

# Returns relative distance from home - FAR AWAY
def tesla_is_far_away():
    return (distance_from_home >= FAR_AWAY_GEO_FENCE_FT)

# Returns relatice location string for logging purposes
def tesla_get_relative_location():
    if tesla_is_vehicle_home():
        return "HOME"
    elif tesla_is_far_away():
        return "FAR AWAY"
    elif tesla_is_vehicle_nearby():
        return "NEARBY"
    elif (tesla_is_vehicle_away()):
        return "AWAY"
    else:
        return "UNKNOWN"

# Determines if the car is arriving home
def tesla_is_arriving_home():
    if ((distance_from_home >= HOME_GEO_FENCE_FT) and (distance_from_home <= ARRIVING_GEO_FENCE_FT)):
        change_vehicle_data_thread_interval(TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_FAST)
        change_myq_door_thread_interval(MYQ_DOOR_STATE_POLL_INTERVAL_SECS)
        start_distance = distance_from_home
        time.sleep(TESLA_LOCATION_DELAY_SECS)
        # Leaving from the west can give the impression the car is arriving due to the roads, so also check the speed
        if ((distance_from_home < start_distance) and (tests_speed <= 25)):
            logging.info("Car is arriving home")
            return True
    return False

# Determines if the car is leaving home    
def tesla_is_leaving_home():
    # The gps location can be vary by up to 15 feet, so first try to catch the car backing out of the garage,
    # then fallback on trying to get the relative location in case the car did not back out of the garage
    if (tesla_is_vehicle_home() and myq_door_open() and (tesla_shift_state == "REVERSE")):
        # There's a 5 second warning built into the garage opener before it starts to close, so only a short delay is needed
        # for the car the pull out of the garage
        change_vehicle_data_thread_interval(TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_FAST)
        change_myq_door_thread_interval(MYQ_DOOR_STATE_POLL_INTERVAL_SECS)
        #time.sleep(TESLA_PULL_OUT_GARAGE_DELAY_SECS)
        logging.info("Car is leaving home")
        return True
    elif ((distance_from_home >= HOME_GEO_FENCE_FT) and (distance_from_home <= AWAY_GEO_FENCE_FT)):
        change_vehicle_data_thread_interval(TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_FAST)
        change_myq_door_thread_interval(MYQ_DOOR_STATE_POLL_INTERVAL_SECS)
        start_distance = distance_from_home
        time.sleep(TESLA_LOCATION_DELAY_SECS)
        if (distance_from_home > start_distance):
            logging.info("Car is leaving home")
            return True
    else:
        change_myq_door_thread_interval(MYQ_DOOR_STATE_CHECK_SECS)
        return False

# Closes the garage door and waits for it to leave the area to prevent hysteresis
def tesla_monitor_car_leaving_home():
    myq_close_door()
    start_distance = distance_from_home
    iterations = 20
    for i in range(iterations):
        if (tesla_is_vehicle_away()):
            logging.info("Car has left home")
            break
        else:
            logging.info("Monitoring the car leaving home...")
            time.sleep(TESLA_LOCATION_DELAY_SECS)

# Opens the garage door and waits for it to arrive home to prevent hysteresis
def tesla_monitor_car_arriving_home():
    iterations = 20
    for i in range(iterations):
        if (distance_from_home <= OPEN_DOOR_GEO_FENCE_FT):
            logging.info("Car is getting close to home...")
            break
        # Catch, in case the car is actually leaving home
        elif (tesla_is_vehicle_away() or tesla_is_far_away()):
            break
        else:
            logging.info("Monitoring the car arriving home...")
            time.sleep(TESLA_LOCATION_DELAY_SECS)
    myq_open_door()
    for j in range(iterations):
        if ((tesla_shift_state == "PARKED") or tesla_is_vehicle_home()):
            logging.info("Car has arrived Home")
            break
        else:
            logging.info("Monitoring the car arriving home...")
            time.sleep(TESLA_LOCATION_DELAY_SECS)

# Converts shift state data to human readable
def shift_state(state):
    if (state is not None):
        if state == "D":
            return "DRIVE"
        elif state == "R":
            return "REVERSE"
        elif state == "N":
            return "NEUTRAL"
        else:
            return "PARKED"
    else:
        return "PARKED"

# Fetches relevant vehicle data
def tesla_get_current_vehicle_state():
    global vehicle_thread_interval_changed

    tick_seconds = 0
    while (True):
        if ((vehicle_thread_interval_changed) or (tick_seconds >= tesla_vehicle_thread_sleep)):
            vehicle_thread_interval_changed = False
            tick_seconds = 0
            tesla_get_driver_present()
            tesla_get_charger_connected()
            tesla_get_drive_state()
        else:
            time.sleep(1)
            tick_seconds += 1

# Main logic to see if a door trigger event is needed
def tesla_check_arriving_leaving():
    # Leaving or Left Home?
    if (tesla_is_leaving_home()):
        tesla_monitor_car_leaving_home()
    # Arriving Home?
    elif (tesla_is_arriving_home()):
        tesla_monitor_car_arriving_home()

# Tesla initialization
def tesla_init():
    tesla_login(tesla_email, tesla_password)
    tesla_get_vehicles()

# Gets the MyQ Auth Token
def myq_login(email, password):
    global myq_auth_token
    global myq_auth_header
    headers = {
        "MyQApplicationId": MYQ_APP_ID
    }
    body = {
        "username": email,
        "password": password
    }
    logging.info("Getting MyQ Auth Token")
    try:
        response = requests.post(MYQ_BASE_API_URL + MYQ_LOGIN, headers=headers, json=body)
        if (response.status_code == 200):
            resp = json.loads(response.text)
            myq_auth_token = resp['SecurityToken']
            myq_auth_header = {
                "SecurityToken": myq_auth_token,
                "MyQApplicationId": MYQ_APP_ID
            }
            logging.info("MyQ Auth Token Aquired")
        else:
            print_error_and_exit("Failed to get MyQ Auth Token: " + str(response.status_code))
    except Exception as e:
        print(e)
        print_error_and_exit("Failed to get MyQ Auth Token: " + str(response.status_code))

# Gets the MyQ Account ID
def myq_get_account_id():
    global myq_account_id

    try:
        response = requests.get(MYQ_BASE_API_URL + MYQ_ACCOUNT_ID, headers=myq_auth_header)
        if (response.status_code == 200):
            resp = json.loads(response.text)
            myq_account_id = resp['Account']['Id']
            logging.info("MyQ Account ID Aquired")
        else:
            print_error_and_exit("Failed to get MyQ Account ID: " + str(response.status_code))
    except Exception as e:
        print(e)
        print_error_and_exit("Failed to get MyQ Account ID: " + str(response.status_code))

# Gets the current state of the MyQ garage door
def myq_get_door_state():
    global myq_device_id
    global myq_door_state

    try:
        url = MYQ_BASE_API_URL + MYQ_DEVICE_LIST
        response = requests.get(url.replace("{account_id}", str(myq_account_id)), headers=myq_auth_header)
        if (response.status_code == 200):
            resp = json.loads(response.text)
            for device in resp["items"]:
                if ("Garage Door Opener" in device["name"]):
                    myq_device_id = str(device["serial_number"])
                    myq_door_state = device['state']['door_state']
                    # Only log the door state if the car is near home
                    if (not tesla_is_far_away()):
                        logging.info("MyQ Door State: " + myq_door_state)
                    return True
        else:
            logging.error("Failed to get MyQ Door State: " + str(response.status_code))
    except:
            logging.exception("Failed to get MyQ Door State")
    return False
        
def myq_get_door_state_with_auth_check():
    global myq_door_thread_interval_changed

    tick_seconds = 0
    while (True):
        if ((myq_door_thread_interval_changed) or (tick_seconds >= myq_door_thread_sleep)):
            myq_door_thread_interval_changed = False
            tick_seconds = 0
             # Retry in case there's an auth error since MyQ doesn't have a token refresh API
            if (not myq_get_door_state()):
                myq_init()
                myq_get_door_state()
        else:
            time.sleep(1)
            tick_seconds += 1

# Changes the MyQ door to "open" or "close"
def myq_change_door_state(state):
    # Action to close the door and a closed door state differ slightly
    if ((state == "close") and (myq_door_state == "closed")):
        return False

    myq_init()
    body = {
        "action_type": state,
    }
    if (state != myq_door_state):
        url = MYQ_BASE_API_URL + MYQ_DEVICE_SET
        try:
            logging.info("Changing MyQ Door State to " + state)
            response = requests.put(url.replace("{account_id}", myq_account_id).replace("{device_id}", myq_device_id), headers=myq_auth_header, json=body)
            if (response.status_code == 204):
                return True
            else:
                logging.error("Unable to Change MyQ Door State: " + str(response.status_code))
        except:
            logging.error("Unable to Change MyQ Door State")
    else:
        logging.error("Tried to change door state to current door state: " + state)
    return False

# Determine if the door is open or opening
def myq_door_open():
    return ((myq_door_state == "open") or (myq_door_state == "opening"))

# Polls the door state while it opens or closes
def myq_poll_door_state():
    start = time.time()
    iterations = 15
    for i in range(iterations):
        if ((time.time() - start) >= MYQ_DOOR_STATE_POLL_TIMEOUT_SECS):
            break
        else:
            logging.info("Polling door state...")
            time.sleep(MYQ_DOOR_STATE_POLL_INTERVAL_SECS)

# Open the garage door
def myq_open_door():
    if(myq_change_door_state("open")):
        myq_poll_door_state()

# Close the garage door
def myq_close_door():
    if(myq_change_door_state("close")):
        myq_poll_door_state()

# MyQ initialization
def myq_init():
    myq_login(myq_email, myq_password)
    myq_get_account_id()

# Initialize and start background threads
def threading_init():
    tesla_vehicle_thread = threading.Thread(name='tesla_vehicle_data', target=tesla_get_current_vehicle_state)
    myq_door_thread = threading.Thread(name='myq_door_data', target=myq_get_door_state_with_auth_check)
    tesla_check_token_expiration_thread = threading.Thread(name='tesla_check_token_expired', target=tesla_check_token_expired)
    watchdog_thread = threading.Thread(name='watchdog', target=watchdog)

    watchdog_thread.daemon = True
    watchdog_thread.start()
    tesla_vehicle_thread.daemon = True
    tesla_vehicle_thread.start()
    myq_door_thread.daemon = True
    myq_door_thread.start()
    tesla_check_token_expiration_thread.daemon = True
    tesla_check_token_expiration_thread.start()

 # Update the sleep interval for the vehicle data thread
def change_vehicle_data_thread_interval(new_interval):
    global vehicle_thread_interval_changed
    global tesla_vehicle_thread_sleep

    if (new_interval != tesla_vehicle_thread_sleep):
        logging.info("Changing Vehicle Data Thread Interval to: " + str(new_interval) + " seconds")
        vehicle_thread_interval_changed = True
        tesla_vehicle_thread_sleep = new_interval

 # Update the sleep interval for the MyQ door thread
def change_myq_door_thread_interval(new_interval):
    global myq_door_thread_interval_changed
    global myq_door_thread_sleep

    if (new_interval != myq_door_thread_sleep):
        logging.info("Changing Door State Thread Interval to: " + str(new_interval) + " seconds")
        myq_door_thread_interval_changed = True
        myq_door_thread_sleep = new_interval

# Main Application Flow
def main_loop():
    threading_init()
    # Add small delay to allow the data to come in
    time.sleep(TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_FAST * 2)
    while (True):
        if (tesla_check_if_fetch_interval_should_change_to_fast()):
            change_vehicle_data_thread_interval(TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_FAST)
        elif (tesla_check_if_fetch_interval_should_change_to_slow()):
            change_vehicle_data_thread_interval(TESLA_FETCH_VEHICLE_DATA_INTERVAL_SECS_SLOW)
        tesla_check_arriving_leaving()
        tesla_check_for_stale_data()
        check_log_file_size()
        time.sleep(1.5)

# Main
def main():
    logging_init()
    logging.info("Starting Magic Garage...")
    parse_input_parameters()
    tesla_init()
    myq_init()
    main_loop()
  
main()
