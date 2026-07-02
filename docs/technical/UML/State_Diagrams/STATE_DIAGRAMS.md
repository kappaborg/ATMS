# ATMS State Diagrams - Complete Specifications
**Date:** October 1, 2025  
**Format:** Mermaid Diagrams (Ready to Export to PNG)

---

## State Diagram 1: Traffic Light State Machine

### Overview
This diagram shows all possible states of a traffic light and the transitions between them, including normal operation and fail-safe modes.

### States:
- **Initialization:** System starting up
- **Red:** Vehicles must stop
- **Green:** Vehicles may proceed
- **Yellow:** Prepare to stop (4 seconds)
- **AllRed:** All directions red (2-3 second clearance)
- **FlashingYellow:** Fail-safe mode (proceed with caution)
- **FlashingRed:** Fail-safe mode (treat as stop sign)

### Mermaid Code:

```mermaid
stateDiagram-v2
    [*] --> Initialization
    
    Initialization --> Red: System Start
    
    state Normal_Operation {
        Red --> Green: Phase Change Command
        Green --> Yellow: Timer Expired<br/>(10-120 seconds)
        Yellow --> Red: Timer Expired<br/>(4 seconds)
    }
    
    Red --> AllRed: Emergency Override
    Green --> AllRed: Emergency Override
    Yellow --> AllRed: Emergency Override
    
    AllRed --> Green: Emergency Cleared<br/>(after 2-3s clearance)
    
    state Fail_Safe_Mode {
        Green --> FlashingYellow: Fail-Safe Activated
        Red --> FlashingRed: Fail-Safe Activated
        Yellow --> FlashingRed: Fail-Safe Activated
        
        FlashingYellow --> FlashingYellow: Continue Flashing
        FlashingRed --> FlashingRed: Continue Flashing
    }
    
    FlashingYellow --> Green: System Restored
    FlashingRed --> Red: System Restored
    
    note right of Green
        Duration: 10-120 seconds
        AI-determined based on traffic
        Minimum: 10s (safety)
        Maximum: 120s (fairness)
    end note
    
    note right of Yellow
        Duration: 4 seconds (fixed)
        Safety standard for stopping
        Not adjustable
    end note
    
    note right of AllRed
        Duration: 2-3 seconds
        Clearance interval
        Ensures intersection is clear
        Required for safety
    end note
    
    note right of FlashingYellow
        Proceed with caution
        No fixed cycle
        Until system restored
    end note
    
    note right of FlashingRed
        Treat as stop sign
        Fail-safe default
        Manual control enabled
    end note
```

---

## State Diagram 2: System Operational States

### Overview
This diagram shows the complete operational state machine of the ATMS system, including startup, normal operation, emergency modes, degraded operation, and fail-safe recovery.

### States:
- **Startup → Initializing → SensorCheck:** System initialization sequence
- **Normal:** AI-driven adaptive traffic control (primary state)
- **Processing → Optimizing → Executing:** Normal operation sub-states
- **Emergency → EmergencyMode:** Emergency vehicle handling
- **Congestion → CongestionMode:** Heavy traffic management
- **Degraded:** Some sensors failed but system operational
- **Failed:** Critical failure detected
- **FailSafe:** Fixed-time operation mode
- **Recovery:** Attempting to restore normal operation
- **Maintenance:** Manual override by operator

### Mermaid Code:

```mermaid
stateDiagram-v2
    [*] --> Startup
    
    Startup --> Initializing: Load Config
    Initializing --> SensorCheck: Init Complete
    
    SensorCheck --> Normal: All Sensors OK
    SensorCheck --> Degraded: Some Sensors Failed
    SensorCheck --> Failed: Critical Sensors Failed
    
    state Normal_Operation {
        Normal --> Processing: Data Received
        Processing --> Optimizing: AI Analysis Complete
        Optimizing --> Executing: Phase Calculated
        Executing --> Normal: Phase Executed
    }
    
    Normal --> Emergency: Emergency Vehicle Detected
    Emergency --> EmergencyMode: Override Activated
    EmergencyMode --> Normal: Emergency Cleared
    
    Normal --> Congestion: High Traffic Detected
    Congestion --> CongestionMode: Queue > 30 Vehicles
    CongestionMode --> Normal: Congestion Resolved
    
    Normal --> Degraded: Sensor Failure
    Degraded --> Normal: Sensor Restored
    Degraded --> Failed: Multiple Failures
    
    Failed --> FailSafe: Critical Failure
    FailSafe --> Recovery: Attempt Recovery
    Recovery --> Normal: Recovery Successful
    Recovery --> FailSafe: Recovery Failed
    
    Normal --> Maintenance: Manual Override
    Maintenance --> Normal: Override Released
    
    note right of Normal
        AI-driven adaptive control
        Real-time optimization
        PPO reinforcement learning
        Rule-based fallback
    end note
    
    note right of EmergencyMode
        Highest priority
        Clear path immediately
        All-red then emergency green
        Monitor until vehicle passes
    end note
    
    note right of CongestionMode
        Aggressive clearing strategy
        Extended green times
        Priority to congested directions
        Alert operators
    end note
    
    note right of Degraded
        Reduced sensor coverage
        Still operational
        Use available sensors
        Alert maintenance
    end note
    
    note right of FailSafe
        Fixed-time operation
        90-second cycle
        Manual control enabled
        Safe default state
    end note
    
    note right of Maintenance
        Operator control
        Fixed timing mode
        Testing and calibration
        System updates
    end note
```

---

## State Diagram 3: Data Processing State

### Overview
This diagram shows how sensor data flows through the system, from reception to decision-making, including all traffic condition states and processing stages.

### States:
- **Waiting:** Idle, ready for data
- **Receiving → Buffering:** Data ingestion
- **Syncing → Synchronized:** Timestamp alignment
- **Detecting → Tracking → Analyzing:** AI processing pipeline
- **LowTraffic/ModerateTraffic/HighTraffic/Congested:** Traffic condition states
- **PriorityMode:** Special handling for congestion
- **Deciding → Complete:** Decision output

### Mermaid Code:

```mermaid
stateDiagram-v2
    [*] --> Waiting
    
    state Data_Ingestion {
        Waiting --> Receiving: Data Available
        Receiving --> Buffering: Store in Queue
        Buffering --> Syncing: Buffer Full<br/>(30 frames)
    }
    
    Syncing --> Synchronized: Timestamps Aligned<br/>(within 50ms)
    Syncing --> Waiting: Sync Failed<br/>(timeout)
    
    state AI_Processing {
        Synchronized --> Detecting: AI Processing Start
        Detecting --> Tracking: Objects Detected<br/>(< 100ms)
        Tracking --> Analyzing: Tracks Updated<br/>(DeepSORT)
    }
    
    state Traffic_Classification {
        Analyzing --> LowTraffic: Queue < 5 vehicles
        Analyzing --> ModerateTraffic: Queue 5-10 vehicles
        Analyzing --> HighTraffic: Queue 10-20 vehicles
        Analyzing --> Congested: Queue > 30 vehicles
    }
    
    LowTraffic --> Deciding: Metrics Ready
    ModerateTraffic --> Deciding: Metrics Ready
    HighTraffic --> Deciding: Metrics Ready
    
    Congested --> PriorityMode: Alert Triggered
    PriorityMode --> Deciding: Strategy Determined
    
    Deciding --> Complete: Decision Made
    Complete --> Waiting: Next Cycle<br/>(2 second loop)
    
    note right of Synchronized
        All sensor data aligned
        Camera + LiDAR + Thermal + Radar
        50ms tolerance
        Ready for AI processing
    end note
    
    note right of Detecting
        YOLOv8 inference
        < 100ms latency (NFR-001)
        8 object classes
        0.8 confidence threshold
        GPU accelerated
    end note
    
    note right of Tracking
        DeepSORT algorithm
        Multi-object tracking
        Speed estimation
        Trajectory prediction
        ±5% speed accuracy
    end note
    
    note right of Analyzing
        Calculate queue lengths
        Estimate wait times
        Measure traffic density
        Detect pedestrians
        Generate metrics
    end note
    
    note right of Congested
        Critical condition
        Queue > 30 vehicles
        Activate priority clearing
        Extended green times
        Alert dashboard
    end note
    
    note right of PriorityMode
        Aggressive strategy
        Max-pressure algorithm
        Focus on clearing queues
        May extend cycle time
        Continuous monitoring
    end note
    
    note right of Deciding
        RL Optimizer (PPO) or
        Rule-based fallback
        Safety checks
        Constraint validation
        Generate phase sequence
    end note
```

---

## State Diagram 4: Fail-Safe System States (Bonus)

### Overview
Detailed state machine for the fail-safe subsystem, showing how the system detects failures and recovers.

### Mermaid Code:

```mermaid
stateDiagram-v2
    [*] --> Monitoring
    
    Monitoring --> Monitoring: System Healthy<br/>(Heartbeat OK)
    
    Monitoring --> FailureDetected: System Not Responding
    
    FailureDetected --> Analyzing: Check Error Type
    
    Analyzing --> MinorFailure: Sensor Error
    Analyzing --> MajorFailure: AI System Error
    Analyzing --> CriticalFailure: Controller Error
    
    MinorFailure --> DegradedMode: Continue with<br/>Remaining Sensors
    DegradedMode --> Monitoring: Sensor Restored
    DegradedMode --> MajorFailure: More Failures
    
    MajorFailure --> ActivateFailSafe: Switch to Fixed-Time
    
    state FailSafe_Operation {
        ActivateFailSafe --> LoadFixedProgram: Load 90s Cycle
        LoadFixedProgram --> FixedTimeMode: Program Loaded
        FixedTimeMode --> FixedTimeMode: Continue Operation<br/>(Safe Default)
    }
    
    FixedTimeMode --> AttemptRecovery: Every 30 seconds
    
    state Recovery_Process {
        AttemptRecovery --> TestSensors: Check Hardware
        TestSensors --> TestAI: Sensors OK
        TestAI --> TestController: AI OK
        TestController --> RecoverySuccess: Controller OK
        
        TestSensors --> RecoveryFailed: Hardware Error
        TestAI --> RecoveryFailed: AI Error
        TestController --> RecoveryFailed: Controller Error
    }
    
    RecoverySuccess --> Monitoring: Resume Normal<br/>Operation
    RecoveryFailed --> FixedTimeMode: Continue Fail-Safe
    
    CriticalFailure --> AlertOperators: Immediate Notification
    AlertOperators --> ManualControl: Operator Intervention
    ManualControl --> Monitoring: Manual Override<br/>Released
    
    note right of Monitoring
        Continuous health checks
        Every 5 seconds
        Check all subsystems
        Maintain uptime 99.9%
    end note
    
    note right of FailSafe_Operation
        Fixed 90-second cycle
        30s North-South
        30s East-West
        4s yellow, 2s all-red
        Safe proven timing
    end note
    
    note right of Recovery_Process
        Systematic checks
        Test each component
        Validate functionality
        Restore if possible
        Log all attempts
    end note
    
    note right of ManualControl
        Operator dashboard
        Manual phase control
        Emergency override
        Testing mode
        Maintenance access
    end note
```

---

## State Diagram 5: Emergency Vehicle Priority States (Bonus)

### Overview
Specialized state machine showing the emergency vehicle detection and priority handling process.

### Mermaid Code:

```mermaid
stateDiagram-v2
    [*] --> NormalOperation
    
    NormalOperation --> NormalOperation: Regular Traffic<br/>Processing
    
    NormalOperation --> EmergencyDetected: Emergency Vehicle<br/>Detected
    
    EmergencyDetected --> DetermineLocation: Analyze Position
    
    DetermineLocation --> IdentifyDirection: Map to<br/>Intersection Approach
    
    IdentifyDirection --> CheckCurrentPhase: Get Light Status
    
    state Decision_Branch {
        CheckCurrentPhase --> ExtendGreen: Already Green in<br/>Emergency Direction
        CheckCurrentPhase --> OverridePhase: Different Direction<br/>Currently Green
    }
    
    ExtendGreen --> MonitorVehicle: Extend Green Time
    
    state Override_Sequence {
        OverridePhase --> SetAllRed: Override Current Phase
        SetAllRed --> WaitClearance: Wait 3 Seconds
        WaitClearance --> SetEmergencyGreen: Set Emergency<br/>Direction Green
    }
    
    SetEmergencyGreen --> MonitorVehicle: Track Progress
    
    MonitorVehicle --> MonitorVehicle: Vehicle Still Present
    MonitorVehicle --> VehiclePassed: Vehicle Cleared<br/>Intersection
    
    VehiclePassed --> LogEvent: Record Event
    LogEvent --> ResumeNormal: Calculate Next Phase
    ResumeNormal --> NormalOperation: Resume AI Control
    
    state Notifications {
        EmergencyDetected --> NotifyDashboard: Alert Operators
        NotifyDashboard --> NotifyDashboard: Show on Map
        VehiclePassed --> ClearAlert: Remove Alert
    }
    
    note right of EmergencyDetected
        AI detection or
        Vehicle beacon signal
        Immediate priority
        Override all rules
    end note
    
    note right of SetAllRed
        Safety critical
        3 second clearance
        Ensure intersection empty
        Then green for emergency
    end note
    
    note right of MonitorVehicle
        Continuous tracking
        Maintain green until passed
        No time limit
        Safety priority
    end note
    
    note right of LogEvent
        Complete audit trail
        Response time
        Route through intersection
        System performance metrics
    end note
```

---

## Export Instructions

### How to Create PNG Images:

#### Method 1: Using Mermaid Live Editor
1. Go to https://mermaid.live/
2. Copy the mermaid code (including ```mermaid tags)
3. Paste into the editor
4. Click "Export" → "PNG"
5. Save with appropriate filename

#### Method 2: Using mermaid-cli
```bash
# Install mermaid-cli
npm install -g @mermaid-js/mermaid-cli

# Convert to PNG
mmdc -i STATE_DIAGRAMS.md -o "Traffic Light State Machine.png" -t default -b transparent

# Or convert all at once
mmdc -i STATE_DIAGRAMS.md -o state_diagrams.png
```

#### Method 3: Using VS Code
1. Install "Markdown Preview Mermaid Support" extension
2. Open this file
3. Right-click on diagram in preview
4. Select "Export to PNG"

### Recommended Filenames:
1. `Traffic Light State Machine.png`
2. `System Operational States.png`
3. `Data Processing State.png`
4. `Fail-Safe System States.png` (bonus)
5. `Emergency Vehicle Priority States.png` (bonus)

---

## Validation Checklist

After creating the PNG images, verify each diagram has:

### ✅ Traffic Light State Machine
- [ ] 7 states (Init, Red, Green, Yellow, AllRed, FlashingYellow, FlashingRed)
- [ ] Initial state indicator (●)
- [ ] Normal operation cycle (Red → Green → Yellow → Red)
- [ ] Emergency transitions (All states → AllRed)
- [ ] Fail-safe transitions (All → Flashing states)
- [ ] Return to normal transitions
- [ ] Timing notes (Green: 10-120s, Yellow: 4s, AllRed: 2-3s)

### ✅ System Operational States
- [ ] 16 states showing full system lifecycle
- [ ] Startup sequence (Startup → Init → SensorCheck)
- [ ] Normal operation loop
- [ ] Emergency handling path
- [ ] Congestion handling path
- [ ] Degraded operation path
- [ ] Fail-safe activation and recovery
- [ ] Maintenance mode
- [ ] Notes explaining each major state

### ✅ Data Processing State
- [ ] 15 states from data ingestion to decision
- [ ] Data ingestion flow (Waiting → Receiving → Buffering)
- [ ] Synchronization process
- [ ] AI processing pipeline (Detecting → Tracking → Analyzing)
- [ ] Traffic classification (Low/Moderate/High/Congested)
- [ ] Priority mode for congestion
- [ ] Decision and completion
- [ ] Loop back to waiting
- [ ] Timing and performance notes

### ✅ Fail-Safe System States (if included)
- [ ] Monitoring → Failure detection → Analysis
- [ ] Failure classification (Minor/Major/Critical)
- [ ] Degraded mode operation
- [ ] Fail-safe activation
- [ ] Fixed-time program
- [ ] Recovery attempts
- [ ] Manual control option

### ✅ Emergency Priority States (if included)
- [ ] Detection → Location → Direction
- [ ] Current phase check
- [ ] Override sequence (All-red → Emergency green)
- [ ] Vehicle monitoring
- [ ] Event logging
- [ ] Resume normal operation
- [ ] Dashboard notifications

---

## Integration with Other Diagrams

### Related Diagrams:
- **Sequence Diagram:** "Emergency Vehicle Detection" shows the same process in time sequence
- **Sequence Diagram:** "System Failure & Recovery" matches the Fail-Safe states
- **Class Diagram:** "Traffic Controller Classes" implements these state machines
- **Activity Diagram:** Shows the activities within each state

### Cross-References:
- State "Normal Operation" = Class "TrafficOptimizer.optimize_loop()"
- State "Detecting" = Class "ObjectDetector.detect_objects()"
- State "FailSafe" = Class "FailSafeSystem.activate()"
- State "EmergencyMode" = Class "EmergencyHandler.handle_emergency()"

---

## Technical Notes

### State Machine Implementation:
In code (Implementation.md), these states are implemented as:
- Enums for state values
- State pattern design
- Event-driven transitions
- Guard conditions in if/else blocks
- Entry/exit actions as methods

### Example Code Mapping:
```python
# State enum
class SystemState(Enum):
    STARTUP = "startup"
    NORMAL = "normal"
    EMERGENCY = "emergency"
    FAILED = "failed"
    FAILSAFE = "failsafe"

# State machine
class ATMSStateMachine:
    def __init__(self):
        self.current_state = SystemState.STARTUP
    
    def transition(self, event):
        # Implement transitions from diagrams
        pass
```

---

**Document Complete**  
**Ready for PNG Export**  
**All 5 State Diagrams Included**

Place exported PNG files in: `/Users/kappasutra/Traffic/UML/State_Diagrams/`

