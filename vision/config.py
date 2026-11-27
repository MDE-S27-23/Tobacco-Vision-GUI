"""User-adjustable calibration and segmentation settings."""

# Measured center-to-center distances between adjacent tray compartments.
# WARNING: 1 inch is an assumption, not verified for the provided trays.
CELL_PITCH_X_IN = 1.0
CELL_PITCH_Y_IN = 1.0
MM_PER_INCH = 25.4

# Repeating grid detector. Use None to infer pitch range from image dimensions.
MIN_CELL_PITCH_PX = None
MAX_CELL_PITCH_PX = None
AUTO_MIN_PITCH_FRACTION = 0.02
AUTO_MAX_PITCH_FRACTION = 0.20
PHASE_IGNORE_EDGE_FRACTION = 0.03
GRID_LINE_SEARCH_FRACTION = 0.08
GRID_EDGE_SCORE_FRACTION = 0.55
MIN_GRID_LINES = 3

# Center each grid line on the separator / plastic margin between cells.
# Turn off to restore the original edge-based line placement.
CENTER_GRID_LINES_ON_MARGINS = True
MARGIN_SEARCH_FRACTION = 0.22      # maximum shift from detected wall edge
MARGIN_RIDGE_THRESHOLD = 0.53      # fraction of wall-to-soil brightness contrast
MARGIN_MIN_CONTRAST = 7.0          # minimum brightness difference (0..255)
MARGIN_MAX_WIDTH_FRACTION = 0.35   # reject implausibly wide bright objects

# Tolerates darker leaves and mixed ambient lighting. Soil and plastic must
# pass ALL the HSV, relative-green and chromatic-green gates to be included.
GREEN_H_MIN = 27
GREEN_H_MAX = 97
GREEN_S_MIN = 35
GREEN_V_MIN = 30
EXCESS_GREEN_MIN = 9
NORMALIZED_EXCESS_GREEN_MIN = 0.075  # (2G-R-B)/(R+G+B)
MIN_GREEN_TO_RED_RATIO = 1.07

CELL_INSET_FRACTION = 0.09
MIN_LEAF_AREA_FRACTION = 0.0015  # one region's fraction of a cell
MIN_PLANT_AREA_FRACTION = 0.004  # summed leaf area needed for plant presence
MAX_LEAF_AREA_FRACTION = 0.64
LEAF_OPEN_KERNEL = 3
LEAF_CLOSE_KERNEL = 3

SPLIT_TOUCHING_LEAVES = True
WATERSHED_PEAK_FRACTION = 0.43
MIN_SPLIT_REGION_AREA_FRACTION = 0.0015
BOUNDARY_REVIEW_MARGIN_PX = 2

SHOW_WINDOWS = False
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 850
DRAW_CELL_LABELS = False
