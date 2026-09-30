"""Interactive destination plates: independent A/mCherry and B layers."""
from copy import deepcopy
import html
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lucia_destination import (assign_destination_wells, build_transfer_preview,
                               clear_destination_wells, create_plate,
                               protein_catalog, remove_plate, rename_plate,
                               validate_layouts)
from reader_plates import WELLS, selected_wells

PALETTE = ['#0F766E', '#7C3AED', '#DB2777', '#2563EB', '#B45309', '#4D7C0F', '#C2410C', '#0369A1']
LAYERS = ['A / mCherry', 'B overlay']


def _protein_name(catalog, group, identity):
    if not identity:
        return 'Empty'
    protein = catalog[group].get(identity)
    if protein is None:
        return f'{identity} (missing calibration)'
    name = protein.get('protein_name') or identity
    return f'{name} ({identity})' if name != identity else identity


def destination_figure(plate, catalog, selected, layer, selection_tool):
    """Keep both layers in hover details while colouring the active layer."""
    group = 'A' if layer == LAYERS[0] else 'B'
    identities = sorted(catalog[group])
    palette = {identity: PALETTE[i % len(PALETTE)] for i, identity in enumerate(identities)}
    colors, hover, text_colors = [], [], []
    for well in WELLS:
        item = plate['wells'].get(well, {})
        a, b = item.get('a_protein_id', ''), item.get('b_protein_id', '')
        control = item.get('a_control', '')
        identity = a if group == 'A' else b
        color, text_color = '#F1F5F9', '#64748B'
        if identity:
            color = palette.get(identity, '#FEE2E2')
            text_color = '#FFFFFF' if identity in palette else '#991B1B'
        elif group == 'A' and control:
            color, text_color = '#BE185D', '#FFFFFF'
        elif a or b or control:
            color = '#DBEAFE'
        elif item.get('label'):
            color = '#FEF3C7'
        a_name = control or _protein_name(catalog, 'A', a)
        detail = f'A / mCherry: {html.escape(a_name)}<br>B overlay: {html.escape(_protein_name(catalog, "B", b))}'
        if control:
            volume = item.get('control_volume_uL')
            detail += f'<br>mCherry: {volume:g} µL' if volume is not None else '<br>mCherry volume: decide later'
        if item.get('label'):
            detail += '<br>' + html.escape(item['label'])
        colors.append(color)
        text_colors.append(text_color)
        hover.append(detail)
    figure = go.Figure(go.Scatter(
        x=[int(well[1:]) for well in WELLS], y=['ABCDEFGH'.index(well[0]) + 1 for well in WELLS],
        mode='markers+text', text=list(WELLS), textfont={'size': 9, 'color': text_colors},
        customdata=[[well] for well in WELLS], hovertext=hover,
        hovertemplate='<b>%{customdata[0]}</b><br>%{hovertext}<extra></extra>',
        marker={'size': 25, 'color': colors,
                'line': {'color': ['#111827' if well in selected else '#FFFFFF' for well in WELLS],
                         'width': [3 if well in selected else 1 for well in WELLS]}},
        selected={'marker': {'opacity': 1}}, unselected={'marker': {'opacity': 0.5}},
        selectedpoints=[i for i, well in enumerate(WELLS) if well in selected] if selected else None,
    ))
    figure.update_layout(
        height=460, margin={'l': 25, 'r': 10, 't': 25, 'b': 10},
        plot_bgcolor='#FFFFFF', paper_bgcolor='#FFFFFF', showlegend=False,
        dragmode={'Drag a box': 'select', 'Click wells': 'pan', 'Lasso': 'lasso'}[selection_tool],
        clickmode='event+select',
        xaxis={'range': [0.3, 12.7], 'tickmode': 'array', 'tickvals': list(range(1, 13)),
               'side': 'top', 'showgrid': False, 'zeroline': False, 'fixedrange': True},
        yaxis={'range': [8.65, 0.35], 'tickmode': 'array', 'tickvals': list(range(1, 9)),
               'ticktext': list('ABCDEFGH'), 'showgrid': False, 'zeroline': False, 'fixedrange': True},
    )
    return figure


def destination_table_rows(plate):
    rows = []
    for well in WELLS:
        item = plate['wells'].get(well, {})
        rows.append({'Well': well, 'A protein': item.get('a_protein_id', ''),
                     'mCherry control': item.get('a_control', '') == 'mCherry',
                     'mCherry (µL)': item.get('control_volume_uL'),
                     'B protein': item.get('b_protein_id', ''), 'Label': item.get('label', '')})
    return rows


def _clean_text(value):
    return '' if value is None or pd.isna(value) else str(value).strip()


def apply_destination_table(layouts, plate_id, rows, catalog):
    """Apply all 96 table rows atomically, preserving unrelated plates."""
    if hasattr(rows, 'to_dict'):
        rows = rows.to_dict('records')
    if len(rows) != len(WELLS) or {row.get('Well') for row in rows} != set(WELLS):
        raise ValueError('The table must contain each well from A1 to H12 exactly once.')
    current_rows = {row['Well']: row for row in destination_table_rows(layouts[plate_id])}
    result = deepcopy(layouts)
    for row in rows:
        well = row['Well']
        a, b, label = (_clean_text(row.get(field)) for field in ('A protein', 'B protein', 'Label'))
        control = bool(row.get('mCherry control', False))
        volume = row.get('mCherry (µL)')
        volume = None if volume is None or pd.isna(volume) else float(volume)
        normalized = {'Well': well, 'A protein': a, 'mCherry control': control,
                      'mCherry (µL)': volume, 'B protein': b, 'Label': label}
        if normalized == current_rows[well]:
            continue
        if a and control:
            raise ValueError(f'{well}: choose an A protein or mCherry, not both.')
        if volume is not None and not control:
            raise ValueError(f'{well}: select mCherry before entering its volume.')
        if not a and not b and not control and not label:
            result = clear_destination_wells(result, plate_id, [well])
        else:
            result = assign_destination_wells(result, plate_id, [well], a_protein_id=a,
                                               b_protein_id=b, label=label, catalog=catalog,
                                               a_control='mCherry' if control else '',
                                               control_volume_uL=volume if volume is not None else '')
    return result


def restore_destination_layout(raw):
    """Read our saved layout, rejecting malformed or nonfinite JSON."""
    def reject_constant(value):
        raise ValueError(f'The saved layout contains an invalid numeric value: {value}.')

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'The saved layout contains a duplicate field: {key}.')
            result[key] = value
        return result

    try:
        record = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_keys)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError('Choose a valid LUCIA plate-layout JSON file.') from exc
    if not isinstance(record, dict) or 'layouts' not in record:
        raise ValueError('This file does not contain saved LUCIA destination layouts.')
    if record.get('format') != 'lucia-destination-layout' or type(record.get('version')) is not int or record['version'] != 1:
        raise ValueError('This LUCIA layout format or version is not supported.')
    return validate_layouts(record['layouts']), record


def render_destination_planner(report, namespace):
    """Render the editable planner and return ``(layouts, transfer_preview)``.

    State keys start ``{namespace}:destination``. Layouts persist through
    calculation changes in this namespace; only an explicit restore replaces
    them. All edits, including deletion and restoration, support one-step undo.
    """
    prefix = f'{namespace}:destination'
    layout_key, undo_key = prefix + ':layouts', prefix + ':undo'
    active_key, pending_key = prefix + ':active', prefix + ':pending'
    revision_key = prefix + ':revision'
    st.session_state.setdefault(layout_key, create_plate({}, 'plate-1', 'LUCIA 1'))
    st.session_state.setdefault(revision_key, 0)
    layouts = st.session_state[layout_key]
    if pending_key in st.session_state:
        st.session_state[active_key] = st.session_state.pop(pending_key)
    if layouts and st.session_state.get(active_key) not in layouts:
        st.session_state[active_key] = next(iter(layouts))
    try:
        catalog = protein_catalog(report)
    except ValueError as exc:
        catalog = {'A': {}, 'B': {}}
        st.error(str(exc))

    def save(updated, active=None):
        st.session_state[undo_key] = (deepcopy(st.session_state[layout_key]), st.session_state.get(active_key))
        st.session_state[layout_key] = updated
        st.session_state[revision_key] += 1
        if active is not None:
            st.session_state[pending_key] = active
        st.rerun()

    st.subheader('LUCIA plate planner')
    st.caption('Place A proteins or mCherry first, then switch to the B overlay. Each well keeps both assignments; several A proteins can share one plate.')
    if prefix + ':notice' in st.session_state:
        st.info(st.session_state.pop(prefix + ':notice'))
    if not catalog['A'] or not catalog['B']:
        st.info('Assign protein groups on the reader plates to make them available here. You can already place mCherry and label wells.')
    active = st.selectbox('LUCIA plate', list(layouts), format_func=lambda identity: layouts[identity]['name'],
                          key=active_key) if layouts else None
    with st.expander('Manage plates'):
        left, right = st.columns(2)
        new_name = left.text_input('New plate name', value=f'LUCIA {len(layouts) + 1}', key=prefix + ':new_name')
        if left.button('Add plate', key=prefix + ':add'):
            number = st.session_state.get(prefix + ':next_id', 2)
            while f'plate-{number}' in layouts:
                number += 1
            identity = f'plate-{number}'
            try:
                updated = create_plate(layouts, identity, new_name)
                st.session_state[prefix + ':next_id'] = number + 1
                save(updated, identity)
            except ValueError as exc:
                st.error(str(exc))
        if active:
            name = right.text_input('Plate name', value=layouts[active]['name'],
                                    key=prefix + f':{active}:rename:{st.session_state[revision_key]}')
            if right.button('Rename plate', key=prefix + ':rename'):
                try:
                    save(rename_plate(layouts, active, name))
                except ValueError as exc:
                    st.error(str(exc))
            if right.button('Delete this plate', key=prefix + ':delete', help='Undo last edit restores a deleted plate.'):
                updated = remove_plate(layouts, active)
                save(updated, next(iter(updated), ''))
    if st.button('Undo last plate edit', key=prefix + ':undo_button', disabled=undo_key not in st.session_state):
        restored, previous_active = st.session_state.pop(undo_key)
        st.session_state[layout_key] = restored
        st.session_state[pending_key] = previous_active
        st.session_state[revision_key] += 1
        st.rerun()

    if active:
        plate = layouts[active]
        plate_prefix = prefix + ':' + active
        selection_key, chart_key = plate_prefix + ':selected', plate_prefix + ':chart'
        st.session_state.setdefault(selection_key, [])
        layer = st.radio('Assignment layer', LAYERS, horizontal=True, key=plate_prefix + ':layer')
        selection_tool = st.radio('Selection tool', ['Drag a box', 'Click wells', 'Lasso'], horizontal=True,
                                  key=plate_prefix + ':selection_tool')

        def handle_selection():
            st.session_state[selection_key] = selected_wells(st.session_state[chart_key], dict.fromkeys(WELLS))

        left, right = st.columns([3, 1.5], gap='large')
        with left:
            st.plotly_chart(destination_figure(plate, catalog, st.session_state[selection_key], layer, selection_tool),
                            key=chart_key, on_select=handle_selection,
                            selection_mode=('points', 'box', 'lasso'), use_container_width=True,
                            config={'displaylogo': False, 'scrollZoom': False,
                                    'modeBarButtonsToRemove': ['zoom2d', 'pan2d', 'zoomIn2d', 'zoomOut2d', 'autoScale2d', 'select2d', 'lasso2d']})
            st.caption('Colours show the active layer · pale blue = the other layer is assigned · pink = mCherry on the A layer · hover to see both layers. Use Shift to add wells.')
        with right:
            st.markdown(f'**Assign {layer}**')
            first, second = st.columns(2)
            first.button('Select all', key=plate_prefix + ':select_all',
                         on_click=lambda: st.session_state.update({selection_key: list(WELLS)}))
            second.button('Deselect all', key=plate_prefix + ':deselect_all',
                          on_click=lambda: st.session_state.update({selection_key: []}))
            selected = st.multiselect('Selected destination wells', list(WELLS), key=selection_key)
            group = 'A' if layer == LAYERS[0] else 'B'
            options = ['keep', 'clear'] + (['mcherry'] if group == 'A' else [])
            options += ['protein:' + identity for identity in catalog[group]]
            protein_key = plate_prefix + ':' + group + ':protein'
            if st.session_state.get(protein_key) not in options:
                st.session_state[protein_key] = 'keep'

            def option_name(value):
                if value == 'keep':
                    return 'Keep current assignment'
                if value == 'clear':
                    return 'Clear this layer'
                if value == 'mcherry':
                    return 'mCherry control'
                return _protein_name(catalog, group, value[len('protein:'):])

            choice = st.selectbox('A protein or control' if group == 'A' else 'B protein', options,
                                   format_func=option_name, key=protein_key)
            control_volume = None
            if choice == 'mcherry':
                set_volume = st.checkbox('Set mCherry volume now', key=plate_prefix + ':set_control_volume')
                if set_volume:
                    control_volume = st.number_input('mCherry per well (µL)', min_value=0.001, max_value=200.0,
                                                      value=1.0, step=0.1, format='%.3f', key=plate_prefix + ':control_volume')
                else:
                    st.caption('Leave the volume undecided while planning.')
            label = st.text_input('Well label (optional)', key=plate_prefix + ':label',
                                  help='A blank label keeps existing labels. Clear labels in the table below.')
            if st.button('Assign selected wells', key=plate_prefix + ':assign', type='primary',
                         disabled=not selected, use_container_width=True):
                fields = {'label': label.strip() or None}
                if group == 'A' and choice == 'mcherry':
                    fields.update(a_control='mCherry', control_volume_uL=control_volume if control_volume is not None else '')
                elif group == 'A' and choice == 'clear':
                    fields.update(a_protein_id='', a_control='', control_volume_uL='')
                elif group == 'B' and choice == 'clear':
                    fields['b_protein_id'] = ''
                elif choice.startswith('protein:'):
                    fields[group.lower() + '_protein_id'] = choice[len('protein:'):]
                try:
                    save(assign_destination_wells(layouts, active, selected, catalog=catalog, **fields))
                except ValueError as exc:
                    st.error(str(exc))
            if st.button('Clear both layers in selected wells', key=plate_prefix + ':clear', disabled=not selected,
                         use_container_width=True):
                save(clear_destination_wells(layouts, active, selected))
        with st.expander('Edit wells manually'):
            st.caption('Edit protein IDs, mCherry controls and labels, then apply the table. Each well can contain one A protein or mCherry, plus one B protein.')
            rows = destination_table_rows(plate)
            a_options = sorted(set(catalog['A']) | {row['A protein'] for row in rows if row['A protein']})
            b_options = sorted(set(catalog['B']) | {row['B protein'] for row in rows if row['B protein']})
            edited = st.data_editor(pd.DataFrame(rows), hide_index=True, width='stretch',
                                    disabled=['Well'], num_rows='fixed',
                                    key=plate_prefix + f':table:{st.session_state[revision_key]}',
                                    column_config={
                                        'A protein': st.column_config.SelectboxColumn('A protein', options=[''] + a_options),
                                        'B protein': st.column_config.SelectboxColumn('B protein', options=[''] + b_options),
                                        'mCherry control': st.column_config.CheckboxColumn('mCherry control'),
                                        'mCherry (µL)': st.column_config.NumberColumn('mCherry (µL)', min_value=0.001, max_value=200.0),
                                    })
            if st.button('Apply table edits', key=plate_prefix + ':apply_table'):
                try:
                    save(apply_destination_table(layouts, active, edited, catalog))
                except ValueError as exc:
                    st.error(str(exc))
    else:
        st.info('Add a plate to start a new layout, or undo the deletion.')

    preview = build_transfer_preview(report, layouts)
    st.caption(f'{len(layouts)} plate(s) · {preview["occupied_wells"]} planned wells. Incomplete layers can be saved and finished later.')
    with st.expander('Transfer preview and remaining setup'):
        if preview['ready']:
            st.success('Both layers have calculated volumes for the assigned wells.')
        elif preview['errors']:
            st.markdown('**Still needed for transfers**')
            for message in preview['errors']:
                st.write('• ' + message)
        for message in preview['warnings']:
            st.info(message)
        if preview['transfers']:
            keys = ['plate_name', 'well', 'stage', 'protein_id', 'protein_name', 'dispense_uL', 'pbs_uL', 'dilution_factor', 'label']
            table = pd.DataFrame([{key: row.get(key) for key in keys} for row in preview['transfers']])
            st.dataframe(table.rename(columns={'plate_name': 'Plate', 'well': 'Well', 'stage': 'Layer',
                                              'protein_id': 'Protein ID', 'protein_name': 'Protein',
                                              'dispense_uL': 'Protein (µL)', 'pbs_uL': 'PBS (µL)',
                                              'dilution_factor': 'Dilution factor', 'label': 'Label'}),
                         hide_index=True, width='stretch')
        if preview['a_usage']:
            st.dataframe(pd.DataFrame(preview['a_usage']).rename(columns={
                'protein_id': 'A protein ID', 'protein_name': 'Protein', 'assigned_wells': 'Planned wells',
                'available_cfe_uL': 'Available CFE (µL)', 'required_cfe_uL': 'Required CFE (µL)',
                'remaining_cfe_uL': 'Remaining CFE (µL)', 'max_samples': 'Available samples'}),
                hide_index=True, width='stretch')
    missing = [message for message in preview['errors'] if 'unknown protein' in message.lower()]
    if missing:
        st.warning('Some assigned protein IDs are missing from the current reader calibrations. Their wells remain saved; update the assignments or restore those calibration groups.')

    metadata = {group: {identity: protein.get('protein_name') or identity
                        for identity, protein in catalog[group].items()} for group in ('A', 'B')}
    export = {'format': 'lucia-destination-layout', 'version': 1,
              'source_sha256': report.get('source_sha256', ''), 'protein_names': metadata, 'layouts': layouts}
    st.download_button('Save LUCIA plate layout', json.dumps(export, indent=2, allow_nan=False),
                       'lucia_plate_layouts.json', 'application/json', key=prefix + ':download')
    with st.expander('Restore a saved LUCIA layout'):
        uploaded = st.file_uploader('Saved plate layout', type=['json'], key=prefix + ':restore_file')
        st.caption('Restoring replaces the current destination plates. Reader calibrations remain in place, and Undo restores the previous destination layout.')
        if st.button('Load saved layout', key=prefix + ':restore', disabled=uploaded is None):
            try:
                restored, record = restore_destination_layout(uploaded.getvalue())
                message = 'Layout restored; volumes use the current workbook.'
                if record.get('source_sha256') != report.get('source_sha256'):
                    message += ' This layout was saved with a different workbook. Check that each protein ID still refers to the intended protein.'
                if record.get('protein_names') != metadata:
                    message += ' The saved protein names differ from the current reader groups; review the assignments.'
                st.session_state[prefix + ':notice'] = message
                save(restored, next(iter(restored), ''))
            except (ValueError, TypeError) as exc:
                st.error(str(exc))
    st.caption('Save the layout to keep it between browser sessions. These assignments will be used for a Flex script once the robot setup is defined.')
    return layouts, preview
