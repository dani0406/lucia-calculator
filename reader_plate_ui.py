"""Python-only interactive 96-well editor for the two reader plates."""
import html
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from lucia_calculations import A_DOSES, B_DOSES
from reader_plates import WELLS, assign_wells, original_layout, selected_wells

PALETTE = ['#0F766E', '#7C3AED', '#DB2777', '#2563EB', '#B45309', '#4D7C0F', '#C2410C', '#0369A1']


def plate_figure(plate, assignments, selected, selection_tool='Drag a box'):
    identities = sorted({a['protein_id'] for a in assignments.values() if a['role'] == 'Calibration'})
    palette = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(identities)}
    colors, hover, text_colors = [], [], []
    for well in WELLS:
        reading = plate['readings'].get(well)
        item = assignments.get(well)
        color, detail, text_color = '#F1F5F9', 'No reading', '#64748B'
        if reading:
            color = '#DBEAFE' if reading['signal'] is not None else '#FEE2E2'
            signal = f"{reading['signal']:,.4g}" if reading['signal'] is not None else 'Invalid reading'
            detail = f"Signal: {signal}<br>Excel: {reading['signal_cell']}"
        if item:
            if item['role'] == 'Calibration':
                color, text_color = palette[item['protein_id']], '#FFFFFF'
                detail += f"<br>{html.escape(item['protein_name'])} ({html.escape(item['protein_id'])})<br>{item['cfe_uL']:g} µL CFE"
            else:
                color = '#FDE68A' if item['role'] == 'Control' else '#CBD5E1'
                detail += f"<br>{item['role']}: {html.escape(item['label'])}"
        colors.append(color)
        text_colors.append(text_color)
        hover.append(detail)
    figure = go.Figure(go.Scatter(
        x=[int(well[1:]) for well in WELLS], y=['ABCDEFGH'.index(well[0]) + 1 for well in WELLS],
        mode='markers+text', text=list(WELLS), textfont={'size': 8, 'color': text_colors},
        customdata=[[well] for well in WELLS], hovertext=hover,
        hovertemplate='<b>%{customdata[0]}</b><br>%{hovertext}<extra></extra>',
        marker={'size': 18, 'color': colors,
                'line': {'color': ['#111827' if w in selected else '#FFFFFF' for w in WELLS],
                         'width': [3 if w in selected else 1 for w in WELLS]}},
        selected={'marker': {'opacity': 1}}, unselected={'marker': {'opacity': 0.5}},
        selectedpoints=[i for i, well in enumerate(WELLS) if well in selected] if selected else None,
    ))
    figure.update_layout(
        height=460, margin={'l': 30, 'r': 12, 't': 30, 'b': 10},
        plot_bgcolor='#FFFFFF', paper_bgcolor='#FFFFFF', font={'color': '#334155'},
        dragmode={'Drag a box': 'select', 'Click wells': 'pan', 'Lasso': 'lasso'}[selection_tool],
        clickmode='event+select', showlegend=False,
        xaxis={'range': [0.3, 12.7], 'tickmode': 'array', 'tickvals': list(range(1, 13)),
               'side': 'top', 'showgrid': False, 'zeroline': False, 'fixedrange': True},
        yaxis={'range': [8.65, 0.35], 'tickmode': 'array', 'tickvals': list(range(1, 9)),
               'ticktext': list('ABCDEFGH'), 'showgrid': False, 'zeroline': False, 'fixedrange': True},
    )
    return figure


def render_reader_plate(plate, group, namespace):
    prefix = f'{namespace}:{group}:{plate["sheet"]}:{plate["signal_column"]}'
    layout_key, selection_key = prefix + ':layout', prefix + ':selected'
    undo_key, chart_key = prefix + ':undo', prefix + ':chart'
    st.session_state.setdefault(layout_key, {})
    st.session_state.setdefault(selection_key, [])
    assignments = st.session_state[layout_key]
    readings = plate['readings']

    def handle_selection():
        st.session_state[selection_key] = selected_wells(st.session_state[chart_key], readings)

    def save_layout(updated):
        st.session_state[undo_key] = st.session_state[layout_key]
        st.session_state[layout_key] = updated

    def start_new_protein():
        used_ids = {item['protein_id'] for item in st.session_state[layout_key].values()
                    if item['role'] == 'Calibration'}
        number = 1
        while f'{group}{number}' in used_ids:
            number += 1
        st.session_state[prefix + ':protein'] = f'{group}{number}'
        st.session_state[prefix + ':name'] = ''
        st.session_state[selection_key] = []

    st.subheader(f'Reader plate {group}')
    st.caption(f'{plate["sheet"]} · {len(readings)} measured wells · signal column {plate["signal_column"]}')
    st.caption('Choose a selection tool below. Use Shift to add wells. Only wells present in the export can be assigned.')
    selection_tool = st.radio('Selection tool', ['Drag a box', 'Click wells', 'Lasso'],
                              horizontal=True, key=prefix + ':selection_tool')
    left, right = st.columns([3, 1.5], gap='large')
    with left:
        st.plotly_chart(plate_figure(plate, assignments, st.session_state[selection_key], selection_tool),
                        key=chart_key, on_select=handle_selection,
                        selection_mode=('points', 'box', 'lasso'), use_container_width=True,
                        config={'displaylogo': False, 'scrollZoom': False,
                                'modeBarButtonsToRemove': ['zoom2d', 'pan2d', 'zoomIn2d', 'zoomOut2d', 'autoScale2d', 'select2d', 'lasso2d']})
        st.caption('Pale blue = unassigned reading · colours = protein groups · yellow = control · grey = excluded or no reading · red = invalid reading')
    with right:
        st.markdown('**Assign selected wells**')
        selection = st.multiselect('Selected wells', [w for w in WELLS if w in readings], key=selection_key)
        wells = [well for well in WELLS if well in selection]
        st.caption('Well order: ' + (', '.join(wells) if wells else 'No wells selected'))
        role = st.selectbox('Well role', ['Calibration', 'Control', 'Exclude'], key=prefix + ':role')
        identity, name, label, doses = '', '', '', None
        dose_text = None
        if role == 'Calibration':
            st.button(f'New {group} protein', key=prefix + ':new_protein', on_click=start_new_protein,
                      help='Start with the next unused ID and select its calibration wells. Saved proteins stay in place.')
            st.caption(f'Add as many {group} proteins as your measured wells support. Names are optional; default labels are {group}1, {group}2, {group}3, …')
            st.session_state[prefix + ':protein'] = st.session_state.get(prefix + ':protein', f'{group}1')
            st.session_state[prefix + ':name'] = st.session_state.get(prefix + ':name', '')
            identity = st.text_input('Protein group ID', key=prefix + ':protein',
                                     help='Each protein has its own ID. Use the same ID to add calibration wells to an existing protein. Reader A and B groups are independent.')
            name = st.text_input('Protein name (optional)', key=prefix + ':name', placeholder='e.g. My protein',
                                 help='Choose any display name, or leave blank to use the ID for a new protein. Adding wells to an existing ID keeps its saved name unless you enter a new one. Names appear on reader graphs, LUCIA plates and exports.')
            st.caption('Select the calibration wells, optionally enter a name, then click Assign wells to save the group. Saved groups become protein choices on every LUCIA plate.')
            mode = st.radio('Assign calibration volumes', ['Same volume / replicates', 'Series in well order'], key=prefix + ':mode')
            if mode == 'Same volume / replicates':
                dose = st.number_input('CFE per well (µL)', min_value=0.0, value=1.0 if group == 'A' else 0.01,
                                       format='%.4f', step=0.0001, key=prefix + ':dose')
                doses = [dose] * len(wells)
            else:
                defaults = A_DOSES if group == 'A' else B_DOSES
                dose_text = st.text_input('CFE volumes (µL), separated by commas',
                                          value=', '.join(f'{v:g}' for v in defaults), key=prefix + ':series')
                st.caption('One volume for each selected well, in the order shown above.')
        else:
            label = st.text_input('Label', placeholder='e.g. mCherry control', key=prefix + ':label')
            st.caption('Labelled wells are saved in the layout and excluded from calibration fits.')
        if st.button('Assign wells', key=prefix + ':assign', type='primary', disabled=not wells, use_container_width=True):
            try:
                if dose_text is not None:
                    try:
                        doses = [float(value.strip()) for value in dose_text.split(',')]
                    except ValueError:
                        raise ValueError('Enter numeric calibration volumes separated by commas.')
                existing_name = next((a['protein_name'] for a in assignments.values()
                                      if a['protein_id'] == identity.strip()), '')
                save_layout(assign_wells(assignments, readings, wells, role, identity,
                                         name or existing_name, doses, label))
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if st.button('Remove selected assignments', key=prefix + ':remove', disabled=not wells, use_container_width=True):
            save_layout({w: a for w, a in assignments.items() if w not in wells})
            st.rerun()
    first, second, third = st.columns(3)
    if first.button(f'Load original {group} layout', key=prefix + ':preset', use_container_width=True,
                    help='Replaces this plate’s assignments using rows 40–47 for A or rows 40–57 for B.'):
        try:
            save_layout(original_layout(plate, group))
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if second.button('Undo last edit', key=prefix + ':undo_button', disabled=undo_key not in st.session_state,
                     use_container_width=True):
        st.session_state[layout_key] = st.session_state.pop(undo_key)
        st.rerun()
    if third.button('Clear plate assignments', key=prefix + ':clear', disabled=not assignments, use_container_width=True):
        save_layout({})
        st.rerun()
    st.caption(f'{len(assignments)} of {len(readings)} measured wells assigned. Unassigned wells do not enter calculations.')
    with st.expander('Well readings and assignments', expanded=False):
        rows = []
        for well in WELLS:
            if well not in readings:
                continue
            reading, item = readings[well], assignments.get(well, {})
            rows.append({'Well': well, 'Signal': reading['signal'], 'Excel cell': reading['signal_cell'],
                         'Role': item.get('role', 'Unassigned'), 'Protein ID': item.get('protein_id', ''),
                         'Protein name': item.get('protein_name', ''), 'CFE (µL)': item.get('cfe_uL'),
                         'Label': item.get('label', ''), 'Reading error': reading['error']})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    return st.session_state[layout_key]
