from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class Category:
    id: Optional[int] = None
    name: str = ""
    active: bool = True


@dataclass
class User:
    id: Optional[int] = None
    username: str = ""
    display_name: str = ""
    role: str = "User"
    active: bool = True


@dataclass
class StockItem:
    id: Optional[int] = None
    code: str = ""
    name: str = ""
    item_type: str = "raw_material"
    unit: str = "kg"
    quantity: Decimal = Decimal("0")
    category_id: Optional[int] = None
    active: bool = True
    date_created: str = ""
    date_modified: str = ""
    created_by: Optional[int] = None
    modified_by: Optional[int] = None
    unit_cost: Decimal = Decimal("0")
    notes: str = ""
