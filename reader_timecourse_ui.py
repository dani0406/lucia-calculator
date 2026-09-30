import pandas as pd
import streamlit as st
from reader_plates import WELLS
from reader_timecourse import read_timecourse, make_timecourse_figure, timecourse_rows


@st.cache_data(show_spinner=False)
def cached_timecourse(raw, sheet):
    return read_timecourse(raw, sheet)


def render_a_timecourse(raw, plate, assignments, namespace):
    st.subheader('Protein A time course')
    try:
        course = cached_timecourse(raw, plate['sheet'])
    except ValueError as exc:
        st.info(str(exc))
        return
    prefix = f'{namespace}:A:{plate["sheet"]}:timecourse'
    measured = [well for well in WELLS if well in course['readings']]
    selection_key = f'{namespace}:A:{plate["sheet"]}:{plate["signal_column"]}:selected'
    selected = st.session_state.get(selection_key, [])
    wells_key = prefix + ':wells'
    with st.expander('Graph options'):
        x, y = st.columns(2)
        x_axis = x.selectbox('Horizontal axis', ['Cycle number', 'Time (s)'] if course['time_available'] else ['Cycle number'],
                             key=prefix + ':axis')
        scale = y.selectbox('Signal scale', ['Logarithmic', 'Linear'], key=prefix + ':scale')
        if st.button('Use wells selected on plate A', disabled=not selected, key=prefix + ':use_selection'):
            st.session_state[wells_key] = [well for well in measured if well in selected]
        wells = st.multiselect('Wells to plot', measured, default=measured, key=wells_key)
        if not course['time_available']:
            st.caption('Elapsed time is unavailable because this sheet has no complete, increasing Time [s] row.')
    if not wells:
        st.info('Choose at least one well in Graph options.')
        return
    log_scale = scale == 'Logarithmic'
    st.plotly_chart(make_timecourse_figure(course, assignments, wells, x_axis, log_scale),
                    key=prefix + ':chart', use_container_width=True,
                    config={'displaylogo': False, 'scrollZoom': False,
                            'toImageButtonOptions': {'format': 'png', 'filename': 'protein_a_timecourse',
                                                     'width': 1200, 'height': 700, 'scale': 2}})
    st.caption(f'{len(wells)} wells · {len(course["cycles"])} cycles · one line per well. Click legend labels to hide or show lines. Hover for exact readings.')
    values = [value for well in wells for value in course['readings'][well]['signals']]
    if any(value is None for value in values):
        st.caption('Missing or invalid readings appear as gaps; they are not interpolated.')
    if log_scale and any(value is not None and value <= 0 for value in values):
        st.warning('Zero and negative readings cannot appear on a logarithmic axis. Switch to Linear to see them; the CSV retains the original values.')
    st.download_button('Download Protein A time-course CSV',
                       pd.DataFrame(timecourse_rows(course, assignments, wells)).to_csv(index=False),
                       'protein_a_timecourse.csv', 'text/csv', key=prefix + ':csv')
