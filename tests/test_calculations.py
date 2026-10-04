from decimal import Decimal

from services import calculate_yield_loss, validate_import_rows


def test_calculate_yield_loss_for_cleaning():
    result = calculate_yield_loss(Decimal('10.000'), Decimal('5.500'), Decimal('175.00'))
    assert result['waste_quantity'] == Decimal('4.500')
    assert result['yield_percentage'] == Decimal('55.000000000000000000')
    assert result['adjusted_cost_per_unit'] == Decimal('31.81818181818181818181818182')


def test_calculate_yield_loss_rejects_zero_original_quantity():
    try:
        calculate_yield_loss(0, 5, 100)
        assert False, 'Expected ValueError'
    except ValueError:
        pass


def test_calculate_yield_loss_rejects_zero_usable_quantity_and_negative_cost():
    for args in [(10, 0, 100), (10, 5, -1), (10, 11, 100)]:
        try:
            calculate_yield_loss(*args)
            assert False, 'Expected ValueError'
        except ValueError:
            pass


def test_stock_import_accepts_cost_per_unit_and_defaults_to_zero():
    rows, errors = validate_import_rows([
        {
            'Stock Item Code': 'FLOUR001',
            'Stock Item Name': 'Bread Flour',
            'Unit': 'kg',
            'Quantity': '4',
            'Cost Per Unit': '2.35',
            'Category': 'Bakery',
        },
        {
            'Stock Item Code': 'SUGAR001',
            'Stock Item Name': 'Sugar',
            'Unit': 'kg',
            'Quantity': '3',
            'Category': 'Bakery',
        },
    ])

    assert errors == []
    assert rows[0]['unit_cost'] == 2.35
    assert rows[1]['unit_cost'] == 0.0
    assert isinstance(rows[0]['quantity'], float)
    assert isinstance(rows[0]['unit_cost'], float)


def test_stock_import_rejects_invalid_or_negative_cost_per_unit():
    rows, errors = validate_import_rows([
        {
            'Stock Item Code': 'BAD001',
            'Stock Item Name': 'Invalid Cost',
            'Unit': 'kg',
            'Quantity': '1',
            'Cost Per Unit': 'not-a-number',
            'Category': 'Bakery',
        },
        {
            'Stock Item Code': 'BAD002',
            'Stock Item Name': 'Negative Cost',
            'Unit': 'kg',
            'Quantity': '1',
            'Cost Per Unit': '-1.00',
            'Category': 'Bakery',
        },
    ])

    assert rows == []
    assert errors == [
        'Row 1: invalid cost per unit for BAD001',
        'Row 2: cost per unit cannot be negative for BAD002',
    ]
