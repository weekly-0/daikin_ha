## Overview

My Daikin D-King (FTKZ-WVM) units can be controlled by an app for control called `Mobile Controller`, which relies on Daikin's cloud servers. Older models were reportedly released with local controller APIs, but newer ones are not.
I was able to do a packet capture after installing the app on my Mac and grab requests for most of the core functionality.

This project provides a Home Assistant custom integration so these units can be controlled from HA (you still need an account created through the official app).
If you want fully local control with a broader feature set, see [ESP32-Faikout](https://github.com/revk/ESP32-Faikout). If you feel uneasy about opening up your air conditioner, this project might be for you instead.

## Current support

- Discover units from your Daikin account
- Create one climate entity per unit
- Control power state (on/off)
- Control HVAC mode:
  - cool
  - dry
  - fan
- Poll and refresh unit state in Home Assistant

## Not currently supported

These features are not currently controllable through this integration because they can't be controlled via the app:

- Powerful Mode
- Intelligent Eye
- Mold-proof (toggle or ad-hoc start)
- Econo/Quiet Mode
- Streamer

If you have a working implementation for these, please open a PR.

## Install

### HACS

1. Add this repository as a custom integration repository in HACS.
2. Install `Daikin Mobile Controller`.
3. Restart Home Assistant.

### Manual

1. Copy `/custom_components/daikin_smartapp` into your HA config directory:
   - `<HA_CONFIG>/custom_components/daikin_smartapp`
2. Restart Home Assistant.

## Configure

1. In Home Assistant, open `Settings -> Devices & Services`.
2. Click `Add Integration`.
3. Select `Daikin Mobile Controller`.
4. Enter the same username/password used in the Daikin `Mobile Controller` app.
