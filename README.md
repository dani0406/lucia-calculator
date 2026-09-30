# LUCIA reader plate calculator

## LUCIA workbook calculation

The website has independent **Reader plate A** and **Reader plate B** editors. The worksheet selectors use the names found in the uploaded workbook. Unedited Tecan exports need one row per well, with 96-well addresses in column A and numeric measurements in column F by default. The measurement column can be changed separately for each reader plate. Duplicate well addresses are rejected rather than merged across measurement blocks. Protein names and calibration volumes are entered in the app; no Excel annotations or formulas are required.

1. Upload the workbook and choose the Protein A and Protein B worksheets.
2. Click wells or drag a box/lasso on each plate. The Selected wells list also supports manual selection.
3. Assign a protein group ID, an optional name, and calibration CFE volumes. Use **Same volume / replicates** for one volume across the selection, or **Series in well order** for one volume per selected well. The displayed order is A1–A12, B1–B12, etc., regardless of drag direction.
4. Assign additional wells to the same ID to extend that protein's calibration. Each measured replicate contributes equally to the regression. At least two distinct calibration volumes are needed per protein. Reader A and B groups are independent, and the number of proteins is flexible.
5. Label controls or exclude wells as needed; neither these wells nor unassigned wells enter the regression. Controls do not trigger background subtraction. Removal, clear and one-step undo operate separately on each reader plate.
6. Set required A sample capacity from 1 to 50 (inclusive; default 18), review results, and download the calculation CSV and JSON record. JSON includes both layouts, signals and source-cell provenance.

**Load original A/B layout** explicitly replaces that plate's assignments using the original rows: A 40–43 and 44–47, B six three-row groups from 40 to 57. Presets use protein IDs A1/A2 and B1–B6, not workbook annotations. For other layouts, assign wells manually.

Layouts persist during session reruns and tab changes, keyed by file contents, worksheet, reader plate and measurement column. A changed file or column starts a separate layout. Reloading the browser or restarting the server can reset the session. Download the record before closing; automatic layout restoration is not implemented.

### Protein A time-course graph

Below the reader A editor, the graph plots one line per measured well across the exported cycles. It defaults to cycle number and a logarithmic signal axis, with fourfold grid spacing matching the supplied example. Names and calibration volumes appear in the legend once wells are assigned. Plotting includes all measured wells by default, independently of their calibration roles.

**Graph options** provides a linear scale, elapsed time in seconds when available, and a well filter. **Use wells selected on plate A** copies the current plate selection into that filter. Legend entries can hide/show lines. The chart toolbar exports a PNG; the time-course CSV includes original readings and source cells. Graph controls do not change the signal column used for volume calculations.

The graph reads `Cycle Nr.` and optional `Time [s]` headers from column A at their actual row positions. Missing/invalid readings create gaps. Zero and negative readings are omitted only on the logarithmic display and retained in the CSV and linear display. Elapsed time is offered only when exported times are complete, nonnegative and strictly increasing; times are never inferred.

### Protein B bar graph

Below the reader B editor, one blue bar per well shows the signal from the selected B measurement column (F by default). The logarithmic axis uses decade gridlines matching the supplied example. The original workbook has 18 measured wells, numbered in numeric plate order from B1–B12 then C1–C6. Numbering is stable when filtering wells. Hover shows the real well address, protein assignment and source cell.

**Graph options** can switch to a linear axis or real well labels and filter the displayed wells, including copying the plate selection. Missing readings keep their empty category positions; nonpositive readings are omitted on the logarithmic display only. The chart toolbar exports a PNG, and **Download Protein B signals CSV** retains raw finite readings and provenance. The graph includes measured wells regardless of calibration role and does not change assignments or calculations.

The interface accepts a Tecan workbook with separate A and B worksheets. `reader_plates.py` turns user-selected wells into calibration inputs; `lucia_calculations.py` applies the existing regression and volume rules. The original fixed-row calculation remains available without Streamlit:

```sh
.venv/bin/python lucia_calculations.py /path/to/readings.xlsx --output-dir /path/to/results
```

It writes `lucia_volumes.csv` and `lucia_results.json`. The original workbook is read only. A uses calibration volumes 1, 0.5, 0.25, 0.125 µL and target signal 100000000. B uses 0.01, 0.001, 0.0001 µL and target signal 400000000. The regression is y=signal and x=CFE µL, using all points without blank subtraction. A capacity is floor(540 / original CFE µL); exactly 18 passes. `--require-more-than-18` selects an optional stricter check. For B, an original volume strictly below 1 µL produces a dilution factor of 10 and a tenfold dispense volume. No repeated dilution is inferred.

Invalid fits, missing readings, insufficient A capacity, and dispense volumes above 200 µL produce errors. The CLI exits with code 2 when calculated records contain errors. R² and extrapolation are reported for review without imposing an unrequested fit-quality threshold. Numerical results retain full precision. These exports are calculation records, not pipette-rounded robot plans.

The sequence is A + PBS to 200 µL, incubate 60 minutes, wash, then B + PBS to 200 µL, incubate 5 minutes, measure. PBS is calculated independently per stage as 200 minus the dispensed protein solution. B-stage PBS assumes no retained wash liquid. Transfer planning awaits source pools, destination assignments, B dilution preparation quantities, wash details, and robot hardware. Existing workbook master-mix formulas are historical calculations and are not used as new transfer instructions.

Launch from this directory:

```sh
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Install dependencies with `python -m pip install -r requirements.txt`. The interface uses Python, Streamlit and Plotly; no custom JavaScript component or build step is needed.

For Streamlit Community Cloud, the repository needs `app.py`, `lucia_ui.py`, `reader_plate_ui.py`, `reader_plates.py`, `reader_timecourse.py`, `reader_timecourse_ui.py`, `reader_barplot.py`, `reader_barplot_ui.py`, `lucia_calculations.py` and `requirements.txt`. Keep `app.py` as the entry point. The new reader files and updated requirements must be included together when publishing.

Run the regression and interaction checks with `python -m unittest -v`. Tests use synthetic in-memory workbooks; no experimental data is required.

The app runs locally. It does not automatically save uploads or experiment history. Download the CSV and JSON record to keep a result.
