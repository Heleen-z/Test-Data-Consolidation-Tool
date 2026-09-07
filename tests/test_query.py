import pandas as pd

from testdata_tool.query import filter_dataset


def test_filter_dataset_preserves_every_matching_row_without_sampling():
    frame = pd.DataFrame(
        {
            "__source_id": ["A"] * 50_000 + ["B"] * 3,
            "__axis_value": list(range(50_000)) + [0, 1, 2],
            "value": list(range(50_003)),
        }
    )

    result = filter_dataset(frame, ["A"], 10, 49_989)

    assert len(result) == 49_980
    assert result["value"].tolist() == list(range(10, 49_990))
