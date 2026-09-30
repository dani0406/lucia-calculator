import pandas as pd
import streamlit as st
from reader_plates import WELLS
from reader_barplot import barplot_rows, make_b_bar_figure


def render_b_barplot(plate, assignments, namespace):
    st.subheader('Protein B signal by well')
    st.caption(f'{plate["sheet"]} · measurement column {plate["signal_column"]} · one bar per well')
    prefix = f'{namespace}:B:{plate["sheet"]}:{plate["signal_column"]}:barplot'
    selection_key = f'{namespace}:B:{plate["sheet"]}:{plate["signal_column"]}:selected'
    measured = [well for well in WELLS if well in plate['readings']]
    selected = st.session_state.get(selection_key, [])
    wells_key = prefix + ':wells'
    with st.expander('Graph options'):
        x, y = st.columns(2)
        labels = x.selectbox('Label wells by', ['Well number', 'Well position'], key=prefix + ':labels')
        scale = y.selectbox('Signal scale', ['Logarithmic', 'Linear'], key=prefix + ':scale')
        if st.button('Use wells selected on plate B', disabled=not selected, key=prefix + ':use_selection'):
            st.session_state[wells_key] = [well for well in measured if well in selected]
        wells = st.multiselect('Wells to plot', measured, default=measured, key=wells_key)
    if not wells:
        st.info('Choose at least one well in Graph options.')
        return
    log_scale = scale == 'Logarithmic'
    st.plotly_chart(make_b_bar_figure(plate, assignments, wells, labels, log_scale),
                    key=prefix + ':chart', use_container_width=True,
                    config={'displaylogo': False, 'scrollZoom': False,
                            'toImageButtonOptions': {'format': 'png', 'filename': 'protein_b_signals',
                                                     'width': 1200, 'height': 700, 'scale': 2}})
    st.caption('Well numbers follow plate order: A1–A12, B1–B12, and so on, counting measured wells only. Hover for the well address, assignment and exact signal.')
    values = [plate['readings'][well]['signal'] for well in measured if well in wells]
    if any(value is None for value in values):
        st.caption('Missing or invalid readings leave an empty bar position.')
    if log_scale and any(value is not None and value <= 0 for value in values):
        st.warning('Zero and negative readings cannot appear on a logarithmic axis. Switch to Linear to see them; the CSV retains the original values.')
    st.download_button('Download Protein B signals CSV',
                       pd.DataFrame(barplot_rows(plate, assignments, wells)).to_csv(index=False),
                       'protein_b_signals.csv', 'text/csv', key=prefix + ':csv')
