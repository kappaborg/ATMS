#!/bin/bash
PLIST=~/Library/LaunchAgents/com.atms.panel-gateway.plist
cur=$(/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:PANEL_USE_SAHI" "$PLIST" 2>/dev/null)
if [ "$cur" = "1" ]; then new=0; state="OFF (fast, whole-frame)"; else new=1; state="ON (aerial/small-object, slower)"; fi
/usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:PANEL_USE_SAHI $new" "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:PANEL_USE_SAHI string $new" "$PLIST"
launchctl kickstart -k gui/$(id -u)/com.atms.panel-gateway
printf 'SAHI is now %s. Gateway restarted.\n' "$state"
