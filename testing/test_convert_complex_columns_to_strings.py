import pyarrow as pa
import json
from overture_to_arcgis.utils.__main__ import convert_complex_columns_to_strings

def test_convert_complex_columns_to_strings():
    # Create a table with struct, list, map, and primitive columns
    struct_array = pa.array([
        {'a': 1, 'b': 2},
        {'a': 3, 'b': 4},
        None
    ], type=pa.struct([('a', pa.int64()), ('b', pa.int64())]))
    list_array = pa.array([
        [1, 2, 3],
        [],
        None
    ], type=pa.list_(pa.int64()))
    map_array = pa.array([
        {'x': 10, 'y': 20},
        {},
        None
    ], type=pa.map_(pa.string(), pa.int64()))
    int_array = pa.array([42, 99, None], type=pa.int64())
    str_array = pa.array(['foo', 'bar', None], type=pa.string())

    table = pa.table({
        'struct_col': struct_array,
        'list_col': list_array,
        'map_col': map_array,
        'int_col': int_array,
        'str_col': str_array
    })

    new_table = convert_complex_columns_to_strings(table)

    # Check struct_col is JSON string
    assert json.loads(new_table['struct_col'][0].as_py()) == {'a': 1, 'b': 2}
    assert json.loads(new_table['struct_col'][1].as_py()) == {'a': 3, 'b': 4}
    assert new_table['struct_col'][2].as_py() == 'null'

    # Check list_col is JSON string
    assert json.loads(new_table['list_col'][0].as_py()) == [1, 2, 3]
    assert json.loads(new_table['list_col'][1].as_py()) == []
    assert new_table['list_col'][2].as_py() == 'null'

    # Check map_col is JSON string
    assert json.loads(new_table['map_col'][0].as_py()) == {'x': 10, 'y': 20}
    assert json.loads(new_table['map_col'][1].as_py()) == {}
    assert new_table['map_col'][2].as_py() == 'null'

    # Check primitive columns unchanged
    assert new_table['int_col'][0].as_py() == 42
    assert new_table['int_col'][1].as_py() == 99
    assert new_table['int_col'][2].as_py() is None
    assert new_table['str_col'][0].as_py() == 'foo'
    assert new_table['str_col'][1].as_py() == 'bar'
    assert new_table['str_col'][2].as_py() is None

def run_tests():
    test_convert_complex_columns_to_strings()
    print("All tests passed.")

if __name__ == "__main__":
    run_tests()

