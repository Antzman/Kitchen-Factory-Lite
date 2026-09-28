from decimal import Decimal

from services import calculate_yield_loss


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
