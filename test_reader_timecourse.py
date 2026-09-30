"""Check time-series alignment and plotted gaps with a small reader export."""
import io
import unittest

from openpyxl import Workbook

from reader_timecourse import make_timecourse_figure, read_timecourse


def timecourse_workbook(times=(0, 60, 120)):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Reader A export'
    # A well-like value before the data header is metadata, not another curve.
    sheet['A3'], sheet['B3'] = 'A1', 999
    sheet['A11'] = 'Cycle Nr.'
    for column, cycle in zip(('B', 'D', 'F'), (1, 3, 5)):
        sheet[f'{column}11'] = cycle
    if times is not None:
        sheet['A12'] = 'Time [s]'
        for column, value in zip(('B', 'D', 'F'), times):
            sheet[f'{column}12'] = value
    for row, well, signals in [
        (15, ' a02 ', (101, 201, 301)),
        (16, 'A10', (102, 'OVER', 302)),
        (17, ' h012 ', (0, -2, 5)),
        (18, 'B1', (None, True, 'NaN')),
    ]:
        sheet.cell(row, 1, well)
        for column, value in zip(('B', 'D', 'F'), signals):
            sheet[f'{column}{row}'] = value
    return workbook


def workbook_bytes(workbook):
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


class ReaderTimecourseTests(unittest.TestCase):
    def read(self, workbook=None):
        workbook = workbook if workbook is not None else timecourse_workbook()
        return read_timecourse(workbook_bytes(workbook), 'Reader A export')

    def test_shifted_headers_keep_cycles_time_and_cell_provenance_aligned(self):
        course = self.read()
        self.assertEqual(course['sheet'], 'Reader A export')
        self.assertEqual(course['cycles'], [
            {'cycle': 1, 'time_s': 0, 'column': 'B'},
            {'cycle': 3, 'time_s': 60, 'column': 'D'},
            {'cycle': 5, 'time_s': 120, 'column': 'F'},
        ])
        self.assertTrue(course['time_available'])
        self.assertEqual(set(course['readings']), {'A2', 'A10', 'H12', 'B1'})
        self.assertEqual(course['readings']['A2']['signals'], [101, 201, 301])
        self.assertEqual(course['readings']['A2']['signal_cells'], ['B15', 'D15', 'F15'])

    def test_missing_invalid_or_overflow_readings_keep_their_positions(self):
        course = self.read()
        self.assertEqual(course['readings']['A10']['signals'], [102, None, 302])
        self.assertEqual(course['readings']['A10']['signal_cells'], ['B16', 'D16', 'F16'])
        self.assertEqual(course['readings']['B1']['signals'], [None, None, None])
        self.assertEqual(course['readings']['H12']['signals'], [0, -2, 5])

    def test_missing_cycle_header_single_cycle_and_duplicate_well_are_rejected(self):
        for alteration in ('header', 'one cycle', 'duplicate'):
            with self.subTest(alteration=alteration):
                workbook = timecourse_workbook()
                sheet = workbook.active
                if alteration == 'header':
                    sheet['A11'] = None
                elif alteration == 'one cycle':
                    sheet['D11'], sheet['F11'] = None, None
                else:
                    sheet['A19'], sheet['B19'] = 'A02', 444
                with self.assertRaises(ValueError):
                    self.read(workbook)

    def test_elapsed_time_requires_complete_strictly_increasing_values(self):
        for times in (None, (0, None, 120), (0, 60, 60), (120, 60, 0)):
            with self.subTest(times=times):
                course = self.read(timecourse_workbook(times))
                self.assertFalse(course['time_available'])
                self.assertEqual([cycle['cycle'] for cycle in course['cycles']], [1, 3, 5])
                if times is None:
                    self.assertEqual([cycle['time_s'] for cycle in course['cycles']], [None] * 3)
                with self.assertRaises(ValueError):
                    make_timecourse_figure(course, {}, ['A2'], x_axis='Time (s)')

    def test_plot_orders_selected_wells_numerically_and_uses_assignment_labels(self):
        course = self.read()
        assignments = {'A2': {'role': 'Calibration', 'protein_id': 'protein-a',
                              'protein_name': 'Sample Alpha', 'cfe_uL': 0.5}}
        figure = make_timecourse_figure(course, assignments, ['H12', 'A10', 'A2'])
        self.assertEqual(len(figure.data), 3)
        self.assertIn('A2', figure.data[0].name)
        self.assertIn('Sample Alpha', figure.data[0].name)
        self.assertIn('0.5', figure.data[0].name)
        self.assertIn('A10', figure.data[1].name)
        self.assertIn('H12', figure.data[2].name)
        for trace in figure.data:
            self.assertEqual(list(trace.x), [1, 3, 5])
            self.assertFalse(trace.connectgaps)
        self.assertEqual(figure.layout.yaxis.type, 'log')

    def test_plot_time_axis_and_log_gaps_do_not_change_the_source_signals(self):
        course = self.read()
        log_figure = make_timecourse_figure(course, {}, ['A10', 'H12'], x_axis='Time (s)')
        self.assertEqual(list(log_figure.data[0].x), [0, 60, 120])
        self.assertEqual(list(log_figure.data[0].y), [102, None, 302])
        self.assertEqual(list(log_figure.data[1].y), [None, None, 5])
        linear_figure = make_timecourse_figure(course, {}, ['H12'], log_scale=False)
        self.assertEqual(list(linear_figure.data[0].y), [0, -2, 5])
        self.assertIn(linear_figure.layout.yaxis.type, ('linear', None))
        self.assertFalse(linear_figure.data[0].connectgaps)
        self.assertEqual(course['readings']['H12']['signals'], [0, -2, 5])


if __name__ == '__main__':
    unittest.main()
