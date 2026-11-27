"""Create overlays for checking the automatically detected grid and leaves."""

import cv2

import config
from models import GridInfo


def draw_grid_overlay(image, grid: GridInfo):
    overlay = image.copy()

    for x in grid.x_lines:
        cv2.line(overlay, (int(x), int(grid.y_lines[0])), (int(x), int(grid.y_lines[-1])), (0, 0, 255), 2)
    for y in grid.y_lines:
        cv2.line(overlay, (int(grid.x_lines[0]), int(y)), (int(grid.x_lines[-1]), int(y)), (255, 0, 0), 2)

    for row in range(grid.rows):
        for column in range(grid.columns):
            cx = int(round((grid.x_lines[column] + grid.x_lines[column + 1]) / 2))
            cy = int(round((grid.y_lines[row] + grid.y_lines[row + 1]) / 2))
            cv2.circle(overlay, (cx, cy), 3, (0, 255, 255), -1)

            if config.DRAW_CELL_LABELS:
                label = f"R{row + 1}C{column + 1}"
                cv2.putText(
                    overlay,
                    label,
                    (grid.x_lines[column] + 4, grid.y_lines[row] + 14),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

    return overlay


def draw_leaf_overlay(image, cell_results, contour_records):
    overlay = image.copy()

    # Cell status marker in the top-left of each cell.
    for cell in cell_results:
        x0, y0, x1, y1 = cell.bounds
        if cell.status == "SEEDLING":
            marker_color = (0, 200, 0)
        elif cell.status == "NO_SEEDLING":
            marker_color = (0, 165, 255)
        else:
            marker_color = (0, 0, 255)

        cv2.rectangle(overlay, (x0 + 2, y0 + 2), (x0 + 8, y0 + 8), marker_color, -1)

    for row, column, leaf_number, contour, leaf in contour_records:
        cv2.drawContours(overlay, [contour], -1, (255, 0, 255), 2)
        label = f"{leaf_number}"
        cv2.putText(
            overlay,
            label,
            (int(round(leaf.center_x_px)), int(round(leaf.center_y_px))),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    return overlay


def show_result_windows(grid_overlay, leaf_mask, leaf_overlay):
    cv2.namedWindow("Detected Tray Grid", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Leaf Mask", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Leaf Measurements", cv2.WINDOW_NORMAL)

    cv2.resizeWindow("Detected Tray Grid", config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
    cv2.resizeWindow("Leaf Mask", config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
    cv2.resizeWindow("Leaf Measurements", config.WINDOW_WIDTH, config.WINDOW_HEIGHT)

    cv2.imshow("Detected Tray Grid", grid_overlay)
    cv2.imshow("Leaf Mask", leaf_mask)
    cv2.imshow("Leaf Measurements", leaf_overlay)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
