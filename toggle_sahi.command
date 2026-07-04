#!/bin/bash
# Toggle SAHI (aerial/small-object detection) on/off in the ATMS gateway.
PLIST=~/Library/LaunchAgents/com.atms.panel-gateway.plist
cur=$(/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:PANEL_USE_SAHI" "$PLIST" 2>/dev/null)
new=$([ "$cur" = "1" ] && echo 0 || echo 1)
/usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:PANEL_USE_SAHI $new" "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:PANEL_USE_SAHI string $new" "$PLIST"
launchctl kickstart -k gui/$(id -u)/com.atms.panel-gateway
echo "SAHI is now $([ "$new" = "1" ] && echo ON (aerial detection, slower) || echo OFF (fast)). Gateway restarted."
