"""Read and plot measured kinetic traces without changing calibration inputs."""
import html
import io
import math
import re

import plotly.graph_objects as go
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from reader_plates import WELLS, normalize_well

LINE_COLORS = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000',
               '#5B9BD5', '#70AD47', '#264478', '#9E480E']


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_timecourse(raw, sheet):
    """Use exported cycle/time headers, never calibration annotations or inferred times."""
    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        if sheet not in workbook.sheetnames:
            raise ValueError(f'Missing worksheet: {sheet}')
        rows = list(workbook[sheet].iter_rows(values_only=True))
    finally:
        workbook.close()
    header_rows = [index for index, row in enumerate(rows)
                   if row and re.fullmatch(r'cycle\s*(nr\.?|number|no\.?)', str(row[0]).strip(), re.I)]
    if len(header_rows) != 1:
        raise ValueError('The time-course graph needs one Cycle Nr. header in column A.')
    header = header_rows[0]
    columns = [(column, value) for column, value in enumerate(rows[header][1:], 1)
               if _number(value) and value > 0 and int(value) == value]
    if len(columns) < 2:
        raise ValueError('The time-course graph needs at least two exported cycles.')
    cycle_numbers = [int(value) for column, value in columns]
    if any(b <= a for a, b in zip(cycle_numbers, cycle_numbers[1:])):
        raise ValueError('Cycle numbers must be unique and increase from left to right.')
    times = None
    readings = {}
    for row_index in range(header + 1, len(rows)):
        row = rows[row_index]
        if not row:
            continue
        if not readings and re.fullmatch(r'time\s*\[s\]', str(row[0]).strip(), re.I):
            times = [row[column] if column < len(row) else None for column, _ in columns]
        well = normalize_well(row[0])
        if not well:
            continue
        if well in readings:
            raise ValueError(f'{sheet}: duplicate well {well} in the time-course readings.')
        values = [row[column] if column < len(row) else None for column, _ in columns]
        readings[well] = {
            'signals': [value if _number(value) else None for value in values],
            'signal_cells': [f'{get_column_letter(column + 1)}{row_index + 1}' for column, _ in columns],
        }
    if not readings:
        raise ValueError('No well readings were found below the cycle header.')
    valid_times = (times is not None and all(_number(value) and value >= 0 for value in times)
                   and all(b > a for a, b in zip(times, times[1:])))
    cycles = [{'cycle': int(value), 'column': get_column_letter(column + 1),
               'time_s': times[index] if times is not None and _number(times[index]) else None}
              for index, (column, value) in enumerate(columns)]
    return {'sheet': sheet, 'cycles': cycles, 'readings': readings, 'time_available': bool(valid_times)}


def trace_name(well, assignment):
    if not assignment:
        return well
    if assignment['role'] == 'Calibration':
        name = assignment.get('protein_name') or assignment['protein_id']
        return f'{well} · {name} · {assignment["cfe_uL"]:g} µL'
    return f'{well} · {assignment.get("label") or assignment["role"]}'


def make_timecourse_figure(course, assignments, wells, x_axis='Cycle number', log_scale=True):
    if x_axis not in ('Cycle number', 'Time (s)'):
        raise ValueError('Choose cycle number or elapsed time in seconds.')
    if x_axis == 'Time (s)' and not course['time_available']:
        raise ValueError('Elapsed time requires a complete, increasing Time [s] row.')
    x_values = [cycle['cycle'] if x_axis == 'Cycle number' else cycle['time_s'] for cycle in course['cycles']]
    figure = go.Figure()
    plotted_values = []
    measured = [well for well in WELLS if well in course['readings']]
    colors = {well: LINE_COLORS[i % len(LINE_COLORS)] for i, well in enumerate(measured)}
    for well in measured:
        if well not in wells:
            continue
        reading = course['readings'][well]
        values = [value if value is not None and (not log_scale or value > 0) else None
                  for value in reading['signals']]
        plotted_values.extend(value for value in values if value is not None)
        figure.add_trace(go.Scatter(
            x=x_values, y=values, mode='lines', connectgaps=False,
            name=html.escape(trace_name(well, assignments.get(well))),
            line={'width': 3, 'color': colors[well]},
            customdata=[[cycle['cycle'], cycle['time_s'], cell]
                        for cycle, cell in zip(course['cycles'], reading['signal_cells'])],
            hovertemplate=('<b>%{fullData.name}</b><br>Cycle: %{customdata[0]}'
                           + ('<br>Time: %{customdata[1]:g} s' if course['time_available'] else '')
                           + '<br>Signal: %{y:,.6g}<br>Excel: %{customdata[2]}<extra></extra>'),
        ))
    y_axis = {'title': {'text': 'Luminescence signal'}, 'type': 'log' if log_scale else 'linear',
              'showgrid': True, 'gridcolor': '#D1D5DB', 'zeroline': False,
              'tickformat': ',', 'separatethousands': True}
    # Match the example's evenly spaced fourfold grid, adapting it to the readings.
    if log_scale and plotted_values:
        lower = math.floor((math.log10(min(plotted_values)) - 5) / math.log10(4)) - 1
        upper = math.ceil((math.log10(max(plotted_values)) - 5) / math.log10(4))
        if -300 <= lower < upper <= 300 and upper - lower <= 16:
            ticks = [100_000 * 4.0 ** index for index in range(lower, upper + 1)]
            y_axis.update(tickmode='array', tickvals=ticks,
                          range=[math.log10(ticks[0]), math.log10(max(plotted_values)) + .18])
    figure.update_layout(
        title={'text': 'Protein A · signal over time', 'x': .5},
        template='plotly_white', height=500, margin={'l': 65, 'r': 20, 't': 60, 'b': 70},
        xaxis={'title': {'text': x_axis}, 'showgrid': False, 'zeroline': False,
               'tickmode': 'array' if x_axis == 'Cycle number' and len(x_values) <= 20 else 'auto',
               'tickvals': x_values if x_axis == 'Cycle number' and len(x_values) <= 20 else None},
        yaxis=y_axis, legend={'orientation': 'h', 'yanchor': 'top', 'y': -.22,
                            'xanchor': 'center', 'x': .5},
        hovermode='closest', uirevision=f'{course["sheet"]}:{x_axis}:{log_scale}',
    )
    return figure


def timecourse_rows(course, assignments, wells):
    """Download the raw readings, including values not visible on a log axis."""
    rows = []
    for well in WELLS:
        if well not in wells or well not in course['readings']:
            continue
        reading = course['readings'][well]
        for cycle, value, cell in zip(course['cycles'], reading['signals'], reading['signal_cells']):
            rows.append({'well': well, 'series': trace_name(well, assignments.get(well)),
                         'cycle': cycle['cycle'], 'time_s': cycle['time_s'],
                         'signal': value, 'sheet': course['sheet'], 'signal_cell': cell})
    return rows
