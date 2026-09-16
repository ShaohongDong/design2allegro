"""ERC data extracted from SKiDL (MIT), Copyright Dave Vandenbout."""

from collections import defaultdict
from enum import IntEnum

OK, WARNING, ERROR = 0, 1, 2
pin_types = IntEnum(
    "pin_types",
    (
        "INPUT",
        "OUTPUT",
        "BIDIR",
        "TRISTATE",
        "PASSIVE",
        "UNSPEC",
        "PWRIN",
        "PWROUT",
        "OPENCOLL",
        "OPENEMIT",
        "PULLUP",
        "PULLDN",
        "NOCONNECT",
        "FREE",
    ),
)

# Various drive levels a pin can output.
# The order of these is important! The first entry has the weakest
# drive and the drive increases for each successive entry.
pin_drives = IntEnum(
    "pin_drives",
    (
        "NOCONNECT",  #  NC pin drive.
        "NONE",  # No drive capability (like an input pin).
        "PASSIVE",  # Small drive capability, but less than a pull-up or pull-down.
        "PULLUPDN",  # Pull-up or pull-down capability.
        "ONESIDE",  # Can pull high (open-emitter) or low (open-collector).
        "TRISTATE",  # Can pull high/low and be in high-impedance state.
        "PUSHPULL",  # Can actively drive high or low.
        "POWER",  # A power supply or ground line.
    ),
)

# Information about the various types of pins:
#   function: A string describing the pin's function.
#   drive: The drive capability of the pin.
#   rcv_min: The minimum amount of drive the pin must receive to function.
#   rcv_max: The maximum amount of drive the pin can receive and still function.
pin_info = {
    pin_types.INPUT: {
        "function": "INPUT",
        "func_str": "INPUT",
        "drive": pin_drives.NONE,
        "max_rcv": pin_drives.POWER,
        "min_rcv": pin_drives.PASSIVE,
    },
    pin_types.OUTPUT: {
        "function": "OUTPUT",
        "func_str": "OUTPUT",
        "drive": pin_drives.PUSHPULL,
        "max_rcv": pin_drives.PASSIVE,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.BIDIR: {
        "function": "BIDIRECTIONAL",
        "func_str": "BIDIR",
        "drive": pin_drives.TRISTATE,
        "max_rcv": pin_drives.POWER,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.TRISTATE: {
        "function": "TRISTATE",
        "func_str": "TRISTATE",
        "drive": pin_drives.TRISTATE,
        "max_rcv": pin_drives.TRISTATE,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.PASSIVE: {
        "function": "PASSIVE",
        "func_str": "PASSIVE",
        "drive": pin_drives.PASSIVE,
        "max_rcv": pin_drives.POWER,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.PULLUP: {
        "function": "PULLUP",
        "func_str": "PULLUP",
        "drive": pin_drives.PULLUPDN,
        "max_rcv": pin_drives.POWER,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.PULLDN: {
        "function": "PULLDN",
        "func_str": "PULLDN",
        "drive": pin_drives.PULLUPDN,
        "max_rcv": pin_drives.POWER,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.UNSPEC: {
        "function": "UNSPECIFIED",
        "func_str": "UNSPEC",
        "drive": pin_drives.NONE,
        "max_rcv": pin_drives.POWER,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.PWRIN: {
        "function": "POWER-IN",
        "func_str": "PWRIN",
        "drive": pin_drives.NONE,
        "max_rcv": pin_drives.POWER,
        "min_rcv": pin_drives.POWER,
    },
    pin_types.PWROUT: {
        "function": "POWER-OUT",
        "func_str": "PWROUT",
        "drive": pin_drives.POWER,
        "max_rcv": pin_drives.PASSIVE,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.OPENCOLL: {
        "function": "OPEN-COLLECTOR",
        "func_str": "OPENCOLL",
        "drive": pin_drives.ONESIDE,
        "max_rcv": pin_drives.TRISTATE,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.OPENEMIT: {
        "function": "OPEN-EMITTER",
        "func_str": "OPENEMIT",
        "drive": pin_drives.ONESIDE,
        "max_rcv": pin_drives.TRISTATE,
        "min_rcv": pin_drives.NONE,
    },
    pin_types.NOCONNECT: {
        "function": "NO-CONNECT",
        "func_str": "NOCONNECT",
        "drive": pin_drives.NOCONNECT,
        "max_rcv": pin_drives.NOCONNECT,
        "min_rcv": pin_drives.NOCONNECT,
    },
    pin_types.FREE: {
        "function": "FREE",
        "func_str": "FREE",
        "drive": pin_drives.NONE,
        "max_rcv": pin_drives.POWER,
        "min_rcv": pin_drives.NOCONNECT,
    },
}


conflict_matrix = defaultdict(lambda: defaultdict(lambda: [OK, ""]))

# Add the non-OK pin connections to the matrix.
conflict_matrix[pin_types.OUTPUT][pin_types.OUTPUT] = [ERROR, ""]
conflict_matrix[pin_types.TRISTATE][pin_types.OUTPUT] = [WARNING, ""]
conflict_matrix[pin_types.UNSPEC][pin_types.INPUT] = [WARNING, ""]
conflict_matrix[pin_types.UNSPEC][pin_types.OUTPUT] = [WARNING, ""]
conflict_matrix[pin_types.UNSPEC][pin_types.BIDIR] = [WARNING, ""]
conflict_matrix[pin_types.UNSPEC][pin_types.TRISTATE] = [WARNING, ""]
conflict_matrix[pin_types.UNSPEC][pin_types.PASSIVE] = [WARNING, ""]
conflict_matrix[pin_types.UNSPEC][pin_types.PULLUP] = [WARNING, ""]
conflict_matrix[pin_types.UNSPEC][pin_types.PULLDN] = [WARNING, ""]
conflict_matrix[pin_types.UNSPEC][pin_types.UNSPEC] = [WARNING, ""]
conflict_matrix[pin_types.PWRIN][pin_types.TRISTATE] = [WARNING, ""]
conflict_matrix[pin_types.PWRIN][pin_types.UNSPEC] = [WARNING, ""]
conflict_matrix[pin_types.PWROUT][pin_types.OUTPUT] = [ERROR, ""]
conflict_matrix[pin_types.PWROUT][pin_types.BIDIR] = [WARNING, ""]
conflict_matrix[pin_types.PWROUT][pin_types.TRISTATE] = [ERROR, ""]
conflict_matrix[pin_types.PWROUT][pin_types.UNSPEC] = [WARNING, ""]
conflict_matrix[pin_types.PWROUT][pin_types.PWROUT] = [ERROR, ""]
conflict_matrix[pin_types.OPENCOLL][pin_types.OUTPUT] = [ERROR, ""]
conflict_matrix[pin_types.OPENCOLL][pin_types.BIDIR] = [WARNING, ""]
conflict_matrix[pin_types.OPENCOLL][pin_types.TRISTATE] = [ERROR, ""]
conflict_matrix[pin_types.OPENCOLL][pin_types.UNSPEC] = [WARNING, ""]
conflict_matrix[pin_types.OPENCOLL][pin_types.PWROUT] = [ERROR, ""]
conflict_matrix[pin_types.OPENEMIT][pin_types.OUTPUT] = [ERROR, ""]
conflict_matrix[pin_types.OPENEMIT][pin_types.BIDIR] = [WARNING, ""]
conflict_matrix[pin_types.OPENEMIT][pin_types.TRISTATE] = [ERROR, ""]
conflict_matrix[pin_types.OPENEMIT][pin_types.UNSPEC] = [WARNING, ""]
conflict_matrix[pin_types.OPENEMIT][pin_types.PWROUT] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.INPUT] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.OUTPUT] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.BIDIR] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.TRISTATE] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.PASSIVE] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.PULLUP] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.PULLDN] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.UNSPEC] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.PWRIN] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.PWROUT] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.OPENCOLL] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.OPENEMIT] = [ERROR, ""]
conflict_matrix[pin_types.NOCONNECT][pin_types.NOCONNECT] = [ERROR, ""]
conflict_matrix[pin_types.PULLUP][pin_types.PULLUP] = [
    WARNING,
    "Multiple pull-ups connected.",
]
conflict_matrix[pin_types.PULLDN][pin_types.PULLDN] = [
    WARNING,
    "Multiple pull-downs connected.",
]
conflict_matrix[pin_types.PULLUP][pin_types.PULLDN] = [
    ERROR,
    "Pull-up connected to pull-down.",
]

# Fill-in the other half of the symmetrical contention matrix by looking
# for entries that != OK at position (r,c) and copying them to position
# (c,r).
cols = list(conflict_matrix.keys())
for c in cols:
    for r in list(conflict_matrix[c].keys()):
        conflict_matrix[r][c] = conflict_matrix[c][r]
