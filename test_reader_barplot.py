"""Check B graph provenance, well identities and logarithmic exclusions."""
import io
import unittest

from openpyxl import Workbook

from reader_barplot import barplot_rows, make_b_bar_figure
from reader_plates import read_reader_plate


def plate_fixture(signals=None, column='F'):
    wells = [f'B{number}' for number in range(1, 13)] + [f'C{number}' for number in range(1, 7)]
    signals = signals if signals is not None else [float(1000 * number) for number in range(1, 19)]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Reader B export'
    # Export order is intentionally reversed; displayed numbers follow plate order.
    for row, (well, signal) in enumerate(reversed(list(zip(wells, signals))), 40):
        sheet.cell(row, 1, well)
        sheet.cell(row, 6, signal)
        sheet.cell(row, 7, 1_000_000 + wells.index(well))
    output = io.BytesIO()
    workbook.save(output)
    return read_reader_plate(output.getvalue(), sheet.title, column), wells


class ReaderBarplotTests(unittest.TestCase):
    def test_eighteen_bars_use_selected_column_with_matching_download_provenance(self):
        plate, wells = plate_fixture()
        figure = make_b_bar_figure(plate, {}, wells)
        rows = barplot_rows(plate, {}, wells)
        self.assertEqual(list(figure.data[0].x), [str(number) for number in range(1, 19)])
        self.assertEqual(list(figure.data[0].y), [1000 * number for number in range(1, 19)])
        self.assertEqual([row['well'] for row in rows], wells)
        self.assertEqual([row['signal_cell'] for row in rows], [f'F{row}' for row in range(57, 39, -1)])
        changed, _ = plate_fixture(column='G')
        changed_figure = make_b_bar_figure(changed, {}, wells)
        changed_rows = barplot_rows(changed, {}, wells)
        self.assertEqual(list(changed_figure.data[0].y), list(range(1_000_000, 1_000_018)))
        self.assertEqual([row['signal'] for row in changed_rows], list(changed_figure.data[0].y))
        self.assertTrue(all(row['signal_column'] == 'G' for row in changed_rows))
        self.assertEqual(changed_rows[0]['signal_cell'], 'G57')
        self.assertIsNone(figure.data[0].base)

    def test_subsets_keep_full_plate_numbers_and_well_labels_with_assignment_metadata(self):
        plate, _ = plate_fixture()
        wells = ['C2', 'B10', 'B2']
        assignments = {'C2': {'role': 'Calibration', 'protein_id': 'B5',
                               'protein_name': 'Example B', 'cfe_uL': .001}}
        numbered = make_b_bar_figure(plate, assignments, wells)
        addressed = make_b_bar_figure(plate, assignments, wells, labels='Well position')
        rows = barplot_rows(plate, assignments, wells)
        self.assertEqual(list(numbered.data[0].x), ['2', '10', '14'])
        self.assertEqual(list(addressed.data[0].x), ['B2', 'B10', 'C2'])
        self.assertEqual([row['well_number'] for row in rows], [2, 10, 14])
        self.assertEqual([row['signal'] for row in rows], [2000, 10000, 14000])
        self.assertEqual(rows[-1]['protein_name'], 'Example B')
        self.assertEqual(rows[-1]['calibration_cfe_uL'], .001)
        self.assertEqual(numbered.data[0].customdata[-1][0], 'C2')
        self.assertIn('Example B', numbered.data[0].customdata[-1][2])

    def test_log_hides_nonpositive_values_without_losing_positions_or_raw_download_values(self):
        plate, wells = plate_fixture([0, -2, 'OVER', None, True, .0001] + [10] * 12)
        wells = wells[:6]
        log_figure = make_b_bar_figure(plate, {}, wells)
        linear_figure = make_b_bar_figure(plate, {}, wells, log_scale=False)
        rows = barplot_rows(plate, {}, wells)
        self.assertEqual(list(log_figure.data[0].x), ['1', '2', '3', '4', '5', '6'])
        self.assertEqual(list(log_figure.data[0].y), [None, None, None, None, None, .0001])
        self.assertEqual(list(linear_figure.data[0].y), [0, -2, None, None, None, .0001])
        self.assertEqual([row['signal'] for row in rows], [0, -2, None, None, None, .0001])
        self.assertEqual(log_figure.layout.yaxis.type, 'log')
        self.assertLess(log_figure.layout.yaxis.range[0], -4)
        self.assertEqual(linear_figure.layout.yaxis.rangemode, 'tozero')
        self.assertIsNone(log_figure.data[0].base)
        self.assertEqual(plate['readings']['B1']['signal'], 0)
        self.assertEqual(plate['readings']['B2']['signal'], -2)


if __name__ == '__main__':
    unittest.main()
