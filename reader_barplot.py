"""Plot the selected Protein B measurement without changing the raw readings."""
import html
import math

import plotly.graph_objects as go
from reader_plates import WELLS


def barplot_rows(plate, assignments, wells):
    measured = [well for well in WELLS if well in plate['readings']]
    rows = []
    for number, well in enumerate(measured, 1):
        if well not in wells:
            continue
        reading, assignment = plate['readings'][well], assignments.get(well, {})
        rows.append({'well_number': number, 'well': well, 'signal': reading['signal'],
                     'protein_id': assignment.get('protein_id', ''),
                     'protein_name': assignment.get('protein_name', ''),
                     'role': assignment.get('role', 'Unassigned'),
                     'calibration_cfe_uL': assignment.get('cfe_uL'),
                     'label': assignment.get('label', ''), 'sheet': plate['sheet'],
                     'signal_column': plate['signal_column'], 'signal_cell': reading['signal_cell']})
    return rows


def make_b_bar_figure(plate, assignments, wells, labels='Well number', log_scale=True):
    if labels not in ('Well number', 'Well position'):
        raise ValueError('Choose well numbers or well positions for the horizontal axis.')
    rows = barplot_rows(plate, assignments, wells)
    values = [row['signal'] if row['signal'] is not None and (not log_scale or row['signal'] > 0)
              else None for row in rows]
    x_values = [str(row['well_number']) if labels == 'Well number' else row['well'] for row in rows]
    details = []
    for row in rows:
        detail = row['protein_name'] or row['protein_id'] or row['label'] or row['role']
        if row['calibration_cfe_uL'] is not None:
            detail += f' · {row["calibration_cfe_uL"]:g} µL CFE'
        details.append([row['well'], row['well_number'], html.escape(detail), row['signal_cell']])
    figure = go.Figure(go.Bar(
        x=x_values, y=values, marker_color='#4472C4', width=.36, customdata=details,
        hovertemplate=('<b>%{customdata[0]}</b> · well %{customdata[1]}<br>%{customdata[2]}'
                       '<br>Signal: %{y:,.6g}<br>Excel: %{customdata[3]}<extra></extra>'),
    ))
    y_axis = {'title': {'text': 'Luminescence signal'}, 'type': 'log' if log_scale else 'linear',
              'showgrid': True, 'gridcolor': '#D1D5DB', 'tickformat': ',', 'zeroline': False}
    positive = [value for value in values if value is not None and value > 0]
    if log_scale and positive:
        lowest = math.log10(min(positive))
        lower = math.floor(lowest)
        if math.isclose(lowest, lower, abs_tol=1e-12):
            lower -= 1  # Keep a value on an exact decade visible above the axis floor.
        upper = max(lower + 1, math.ceil(math.log10(max(positive))))
        y_axis.update(range=[lower, upper], dtick=1)
    elif not log_scale:
        y_axis['rangemode'] = 'tozero'
    figure.update_layout(
        title={'text': 'Protein B · signal by well', 'x': .5},
        template='plotly_white', height=460, margin={'l': 75, 'r': 20, 't': 60, 'b': 65},
        xaxis={'title': {'text': labels}, 'type': 'category', 'categoryorder': 'array',
               'categoryarray': x_values, 'showgrid': False, 'tickangle': 0},
        yaxis=y_axis, showlegend=False,
        uirevision=f'{plate["sheet"]}:{plate["signal_column"]}:{labels}:{log_scale}',
    )
    return figure
