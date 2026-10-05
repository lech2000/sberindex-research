from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"economic-atlas/src"))
from atlas_a13 import compare


def test_regression_counts_are_exact_and_numeric_tolerance_is_explicit():
    assert not compare({"n":1896,"x":.123456789},{"n":1896,"x":.123456790})
    assert compare({"n":1896},{"n":1895})
    assert compare({"x":.1},{"x":.2})
    assert compare({"status":"NA","x":None},{"status":"COMPUTED","x":0.})
