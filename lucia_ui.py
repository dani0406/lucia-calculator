import io
import hashlib
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from lucia_calculations import summary_rows
from reader_plates import read_reader_plate, calculate_reader_plates
from reader_plate_ui import render_reader_plate
from reader_timecourse_ui import render_a_timecourse
from reader_barplot_ui import render_b_barplot

EXAMPLE_PATH = Path('/Volumes/bosse-grp/Group_Data/AVA NL assay/Aria_Binder/20260915_AD_JK_binders_3/20260917_JK_AD_DL_LUCIA.xlsx')


@st.cache_data(show_spinner=False)
def workbook_sheets(raw):
    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        return workbook.sheetnames
    finally:
        workbook.close()


@st.cache_data(show_spinner=False)
def cached_reader_plate(raw, sheet, signal_column):
    return read_reader_plate(raw, sheet, signal_column)


def render_lucia():
    st.title('LUCIA · Reader plates')
    st.caption('Upload readings → assign wells on reader plates A and B → calculate protein volumes')
    uploaded = st.file_uploader('Upload the Tecan Excel workbook', type=['xlsx'], key='lucia_upload')
    use_example = False
    if uploaded is None and EXAMPLE_PATH.exists():
        use_example = st.checkbox('Use the supplied 20260917 workbook', value=True)
    if uploaded is None and not use_example:
        st.info('Upload the unedited workbook containing the A and B measurement sheets. Protein names and calibration annotations are entered here.')
        return
    raw = uploaded.getvalue() if uploaded else EXAMPLE_PATH.read_bytes()
    workbook_key = hashlib.sha256(raw).hexdigest()[:16]
    st.caption(f'Workbook: {uploaded.name if uploaded else EXAMPLE_PATH.name}')
    try:
        names = workbook_sheets(raw)
        if len(names) < 2:
            st.error('This workbook needs separate worksheets for Protein A and Protein B.')
            return
        a, b = st.columns(2)
        a_sheet = a.selectbox('Protein A', names, index=0, key=f'{workbook_key}:a_sheet')
        b_sheet = b.selectbox('Protein B', names, index=1, key=f'{workbook_key}:b_sheet')
        if a_sheet == b_sheet:
            st.error('Choose different A and B worksheets.')
            return
        with st.expander('Reader export settings'):
            st.caption('Well addresses are read from column A. Column F is the original cycle-5 signal. Change the measurement column if needed; changing it starts a separate layout.')
            a, b = st.columns(2)
            columns = list('BCDEFGHIJK')
            a_column = a.selectbox('Signal column for reader A', columns, index=4, key=workbook_key + ':a_column')
            b_column = b.selectbox('Signal column for reader B', columns, index=4, key=workbook_key + ':b_column')
        plates = {'A': cached_reader_plate(raw, a_sheet, a_column),
                  'B': cached_reader_plate(raw, b_sheet, b_column)}
    except Exception as exc:
        st.error(f'Could not read this workbook: {exc}')
        return
    assignments = {}
    tabs = st.tabs(['Reader plate A', 'Reader plate B'])
    for group, tab in zip(('A', 'B'), tabs):
        with tab:
            assignments[group] = render_reader_plate(plates[group], group, workbook_key)
            if group == 'A':
                render_a_timecourse(raw, plates[group], assignments[group], workbook_key)
            else:
                render_b_barplot(plates[group], assignments[group], workbook_key)
    st.divider()
    minimum = st.slider('Required samples per A protein', min_value=1, max_value=50, value=18, step=1)
    st.caption(f'Each A protein must provide at least {minimum} samples. Exactly {minimum} passes.')
    report = calculate_reader_plates(plates, assignments, minimum)
    st.subheader('Calculated volumes')
    if not report['proteins']:
        st.info('Select calibration wells and assign their protein group and CFE volumes. For the original workbook layout, use the preset button on each reader plate.')
    else:
        rows = summary_rows(report)
        for row, protein in zip(rows, report['proteins']):
            row['reader_plate'] = protein['group']
            row['reader_wells'] = ', '.join(protein['reader_wells'])
        table = pd.DataFrame(rows)
        labels = {'protein_id': 'Protein ID', 'protein_name': 'Protein name', 'target_pmol': 'Target (pmol)',
                  'cfe_equivalent_uL': 'Original CFE equivalent (µL)', 'dilution_factor': 'Dilution factor',
                  'dispense_uL': 'Volume to dispense (µL)', 'pbs_uL': 'PBS (µL)', 'stage': 'Addition stage',
                  'incubation_minutes': 'Incubation (min)', 'max_samples': 'Available samples',
                  'r_squared': 'Calibration R²', 'extrapolated': 'Extrapolated', 'error': 'Error',
                  'reader_plate': 'Reader plate', 'reader_wells': 'Calibration wells'}
        st.dataframe(table.rename(columns=labels), hide_index=True, width='stretch')
        for error in report['errors']:
            st.error(error)
        present = {protein['group'] for protein in report['proteins']}
        if not report['errors']:
            if present == {'A', 'B'}:
                st.success('Assigned protein groups pass the volume and A sample-capacity checks.')
            else:
                st.info('Partial results: assign calibration groups on both reader plates to complete A and B calculations.')
        if any(p.get('extrapolated') for p in report['proteins']):
            st.caption('Some targets require extrapolation beyond the measured calibration range; inspect the fitted lines before using results.')
        st.download_button('Download calculation CSV', table.to_csv(index=False), 'lucia_volumes.csv', 'text/csv')
    st.download_button('Download calculation record and plate layouts', json.dumps(report, indent=2, allow_nan=False),
                       'lucia_results.json', 'application/json')
    st.caption('Layouts stay in this browser session during edits. Download the record to keep assignments and readings; refreshing the page can reset the session.')
    with st.expander('Calculation rules and details'):
        st.markdown('**A:** target signal 100,000,000 for 20 pmol; 540 µL CFE available per protein. **B:** target signal 400,000,000 for 40 pmol.')
        st.caption('CFE µL = (target signal − intercept) / slope. Every assigned calibration well contributes equally, including replicates. At least two distinct calibration volumes are needed per protein. No blank subtraction is applied.')
        st.caption('For B only: original CFE equivalent < 1 µL → tenfold dilution and ten times the dispense volume. Exactly 1 µL stays undiluted. No additional dilution is applied automatically.')
        st.markdown('**A + PBS to 200 µL → incubate 60 minutes → wash → B + PBS to 200 µL → incubate 5 minutes → measure.**')
        st.caption('PBS is calculated separately for each stage and assumes no retained wash liquid. Sample counts use full-precision volumes.')
        st.json(report['proteins'])
    st.caption('Reader plates identify calibration measurements. Robot source wells, destination plates, pooling and wash settings still need their own setup. The uploaded workbook is not modified; no robot protocol is generated here.')
