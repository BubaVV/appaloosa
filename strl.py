import streamlit as st
from streamlit_drawable_canvas import st_canvas
import pandas as pd
from PIL import Image
import random

CANVAS_WIDTH = 1200
CANVAS_HEIGHT = 800

SELECT_MODES = {
    "Frontline": "line",
    "Spot": "point",
    "Baseline": "point",
    "Edit": "transform"
}

HELP_MESSAGE = {
    "Frontline": "Select finish line of solvent",
    "Spot": "Select centers of every spot of interest",
    "Baseline": "Select start point for every spot of interest",
    "Edit": "Edit spots and lines. Double click to delete object"
}

drawing_mode = st.sidebar.selectbox(
    "Feature selector:", SELECT_MODES.keys()
)

st.sidebar.write(HELP_MESSAGE[drawing_mode])

if drawing_mode in ['Spot', 'Baseline']:
    point_display_radius = st.sidebar.slider("Point display radius: ", 1, 25, 3)
else:
    point_display_radius = 0
uploaded_img = st.sidebar.file_uploader("Plate image:", type=["png", "jpg"])

if uploaded_img:
    orig_img = Image.open(uploaded_img)
    orig_img.thumbnail((CANVAS_WIDTH, CANVAS_HEIGHT))
    plate_size = orig_img.size

if not uploaded_img:
    st.stop()

canvas_result = st_canvas(
    fill_color="rgba(255, 165, 0, 0.3)",  # Fixed fill color with some opacity
    stroke_width=3,
    stroke_color='#000000',
    background_color='#eee',
    background_image=orig_img if orig_img else None,
    update_streamlit=True,
    width=plate_size[0],
    height=plate_size[1],
    initial_drawing=st.session_state.get('initial_drawing', None),
    drawing_mode=SELECT_MODES[drawing_mode],
    point_display_radius=point_display_radius if drawing_mode in ['Spot', 'Baseline'] else 0,
    # key='canvas_{}'.format(random.randint(0,10000)),
    # key = 'canvas',
    key = st.session_state.get('key', 'canvas')
)

canvas_result_processed = None
if drawing_mode == 'Frontline' and canvas_result.json_data and canvas_result.json_data['objects']:
    fresh_line = canvas_result.json_data['objects'][-1]
    if fresh_line['type'] == 'line':
        initial_drawing = dict(canvas_result.json_data)
        initial_drawing['objects'] = [obj for obj in canvas_result.json_data['objects'] if
                           obj['type'] != 'line']
        initial_drawing['objects'].append(fresh_line)
        st.session_state['initial_drawing'] = initial_drawing
        st.session_state['key'] = f"canvas_{random.randint(0, 1000)}"
        canvas_result_processed = initial_drawing

if not canvas_result_processed:
    canvas_result_processed = canvas_result.json_data

# Do something interesting with the image data and paths
# if canvas_result.image_data is not None:
#     st.image(canvas_result.image_data)
if canvas_result_processed is not None:
    objects = pd.json_normalize(canvas_result_processed[
                                    "objects"])  # need to convert obj to str
    # because PyArrow
    for col in objects.select_dtypes(include=['object']).columns:
        objects[col] = objects[col].astype("str")
    st.dataframe(objects)

if canvas_result.json_data and canvas_result.json_data['objects']:
    pass
else:
    st.stop()