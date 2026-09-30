import io
import hashlib
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from lucia_calculations import calculate_workbook, summary_rows

EXAMPLE_PATH = Path('/Volumes/bosse-grp/Group_Data/AVA NL assay/Aria_Binder/20260915_AD_JK_binders_3/20260917_JK_AD_DL_LUCIA.xlsx')


def render_lucia():
    st.title('LUCIA CFE calculation')
    st.caption('Luminescence calibration · column F · two A proteins and six B proteins')
    uploaded = st.file_uploader('Upload the Tecan Excel workbook', type=['xlsx'], key='lucia_upload')
    use_example = False
    if uploaded is None and EXAMPLE_PATH.exists():
        use_example = st.checkbox('Use the supplied 20260917 workbook', value=True)
    if uploaded is None and not use_example:
        st.info('Upload the workbook containing the A and B measurement sheets.')
        return
    raw = uploaded.getvalue() if uploaded else EXAMPLE_PATH.read_bytes()
    workbook_key = hashlib.sha256(raw).hexdigest()[:16]
    st.caption(f'Workbook: {uploaded.name if uploaded else EXAMPLE_PATH.name}')
    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        names = workbook.sheetnames
        workbook.close()
        if len(names) < 2:
            st.error('This workbook needs separate worksheets for Protein A and Protein B.')
            return
        st.caption('Select the Protein A and Protein B worksheets using the names found in this workbook.')
        a, b = st.columns(2)
        with a:
            a_sheet = st.selectbox('Protein A', names, index=0, key=f'{workbook_key}:a_sheet', help='Choose the worksheet containing the Protein A readings.')
        with b:
            b_sheet = st.selectbox('Protein B', names, index=1, key=f'{workbook_key}:b_sheet', help='Choose the worksheet containing the Protein B readings.')
        if a_sheet == b_sheet:
            st.error('Choose different A and B worksheets.')
            return
        minimum = st.slider('Required samples per A protein', min_value=1, max_value=50, value=18, step=1)
        st.caption(f'Each A protein must provide at least {minimum} samples. Exactly {minimum} passes.')
        protein_names = {}
        input_key = workbook_key + ':' + a_sheet + ':' + b_sheet
        with st.expander('Protein names (optional)'):
            st.caption('No names are needed in Excel. Leave these blank to use A1, A2 and B1–B6. Names entered here appear in the results and downloads.')
            a, b = st.columns(2)
            with a:
                for i in range(1, 3):
                    identity = f'A{i}'
                    protein_names[identity] = st.text_input(f'{identity} name', placeholder=identity, key=f'{input_key}:{identity}')
            with b:
                for i in range(1, 7):
                    identity = f'B{i}'
                    protein_names[identity] = st.text_input(f'{identity} name', placeholder=identity, key=f'{input_key}:{identity}')
        report = calculate_workbook(raw, a_sheet, b_sheet, minimum_samples=minimum, protein_names=protein_names)
    except Exception as exc:
        st.error(f'Could not calculate this workbook: {exc}')
        return
    st.markdown('**A:** 1, 0.5, 0.25, 0.125 µL at rows 40–43 and 44–47. Target signal: 100,000,000 for 20 pmol. Available CFE: 540 µL per A protein.')
    st.markdown('**B:** 0.01, 0.001, 0.0001 µL in six consecutive three-row groups starting at row 40. Target signal: 400,000,000 for 40 pmol.')
    st.caption('CFE µL = (target signal − intercept) / slope. The prescribed calibration volumes are used directly, even if the M/N cells are empty. No blank subtraction is applied.')
    rows = summary_rows(report)
    table = pd.DataFrame(rows)
    labels = {'protein_id':'Protein ID', 'protein_name':'Protein name', 'target_pmol':'Target (pmol)',
              'cfe_equivalent_uL':'Original CFE equivalent (µL)', 'dilution_factor':'Dilution factor',
              'dispense_uL':'Volume to dispense (µL)', 'pbs_uL':'PBS (µL)', 'stage':'Addition stage',
              'incubation_minutes':'Incubation (min)', 'max_samples':'Available samples',
              'r_squared':'Calibration R²', 'extrapolated':'Extrapolated', 'error':'Error'}
    st.subheader('Calculated volumes')
    st.dataframe(table.rename(columns=labels), hide_index=True, width='stretch')
    st.caption('A1/A2 and B1–B6 are protein-group IDs, not source-well assignments. Sample counts use full-precision volumes; display rounding does not change the calculation.')
    for error in report['errors']:
        st.error(error)
    if not report['errors']:
        st.success('Both A proteins meet the selected sample-capacity rule. All calculated dispense volumes are within 200 µL.')
    st.caption('For B only: original CFE equivalent < 1 µL → tenfold dilution and ten times the dispense volume. Exactly 1 µL stays undiluted. No additional dilution is applied automatically.')
    if any(p.get('extrapolated') for p in report['proteins']):
        st.caption('The requested target signals require extrapolation beyond the measured calibration range; the specified formulas are applied without alteration.')
    st.subheader('Addition sequence')
    st.markdown('**A + PBS to 200 µL → incubate 60 minutes → wash → B + PBS to 200 µL → incubate 5 minutes → measure.**')
    st.caption('PBS = 200 µL minus the volume dispensed in that stage. B PBS volumes assume no retained wash liquid. A and B volumes are not added together when calculating PBS.')
    st.info('Robot setup pending: source wells and pooling volumes, destination wells, B dilution preparation quantity, wash procedure, and deck/pipettes. The reader well names are not automatically used as CFE source wells.')
    a, b = st.columns(2)
    a.download_button('Download calculation CSV', table.to_csv(index=False), 'lucia_volumes.csv', 'text/csv')
    b.download_button('Download calculation record', json.dumps(report, indent=2), 'lucia_results.json', 'application/json')
    with st.expander('Calibration readings and fitted lines'):
        st.json(report['proteins'])
    st.caption('Calculation outputs only. No robot protocol is generated in this mode. The uploaded workbook is not modified or automatically saved.')
