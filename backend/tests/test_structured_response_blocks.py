from app.orchestration.schemas import (
    AnswerPresentation,
    CalculationWidget,
    ComposedAnswer,
    PresentationChart,
    PresentationSeries,
    SourceCitation,
)


def test_legacy_answer_fields_generate_ordered_structured_blocks():
    answer = ComposedAnswer(
        text="A grounded comparison. [REF-1]",
        citations=[SourceCitation(ref_id="REF-1", source_id="src-1", title="Source", url=None)],
        presentation=AnswerPresentation(
            layout="data_visualization",
            charts=[PresentationChart(
                chart_id="chart-1", title="Region", categories=["North", "South"],
                series=[PresentationSeries(name="Value", values=["10", "20"])],
            )],
        ),
    )

    assert [block.type for block in answer.blocks] == ["markdown", "visualization", "citations"]
    assert answer.blocks[1].resource_ids == ["chart-1"]
    assert answer.response_mode == "compound"


def test_calculation_block_references_governed_widget_without_copying_values():
    widget = CalculationWidget(
        formula_id="working_capital", formula_name="Working capital",
        formula_display="assets - liabilities", methodology_reference="formula-registry",
        output_label="Working capital", output_value="130000", output_unit="USD",
        calculation_id="calc-1",
    )
    answer = ComposedAnswer(text="Verified result.", calculation_widget=widget)

    assert [block.type for block in answer.blocks] == ["markdown", "calculation"]
    assert answer.blocks[1].resource_ids == ["calc-1"]
    assert answer.blocks[1].content is None
    assert answer.response_mode == "calculation"


def test_explicit_blocks_remain_authoritative_for_forward_compatibility():
    answer = ComposedAnswer(
        text="Legacy text",
        blocks=[{"id": "custom", "type": "markdown", "content": "Planned text", "resource_ids": []}],
    )
    assert len(answer.blocks) == 1
    assert answer.blocks[0].content == "Planned text"
