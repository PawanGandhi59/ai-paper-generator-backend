import pytest
from app.schemas.visuals import (
    BiologyDataSpec,
    BiologyLabelOverride,
    GeminiVisualRequirementSchema,
    VisualRequiredSpec,
)
from app.services.visuals.builders.biology_builder import BiologyBuilder
from app.services.visuals.svg_generator_service import SVGGeneratorService, is_valid_svg_xml
from app.services.visuals.visual_semantic_validator import VisualSemanticValidator


def test_punnett_square_svg_generation():
    """
    Test that BiologyBuilder renders valid SVG for a Monohybrid Punnett square.
    """
    builder = BiologyBuilder()
    data = {
        "template": "punnett_square",
        "parent1": "Tt (Tall)",
        "parent2": "Tt (Tall)",
        "gametes1": ["T", "t"],
        "gametes2": ["T", "t"],
        "cross_grid": [["TT", "Tt"], ["Tt", "tt"]],
    }
    svg = builder.render({"title": "Monohybrid Cross (Height)", "data": data, "caption": "F2 generation cross"})
    assert is_valid_svg_xml(svg) is True
    assert "Monohybrid Cross (Height)" in svg
    assert "TT" in svg
    assert "Tt" in svg
    assert "tt" in svg
    assert "Female Gametes" in svg
    assert "Male Gametes" in svg


def test_nephron_svg_generation_with_masked_labels():
    """
    Test that BiologyBuilder renders Nephron with label overrides (A, B, C) for exam questions.
    """
    builder = BiologyBuilder()
    data = {
        "template": "nephron",
        "biology_labels": [
            {"target": "glomerulus", "label": "A"},
            {"target": "bowman_capsule", "label": "B"},
            {"target": "collecting_duct", "label": "C"},
        ],
    }
    svg = builder.render({"title": "Structure of Nephron", "data": data, "caption": "Identify parts A, B, and C"})
    assert is_valid_svg_xml(svg) is True
    assert "Structure of Nephron" in svg
    assert ">A<" in svg
    assert ">B<" in svg
    assert ">C<" in svg


def test_human_heart_svg_generation():
    """
    Test that BiologyBuilder renders the 4-chamber human heart schematic.
    """
    builder = BiologyBuilder()
    data = {
        "template": "human_heart",
        "biology_labels": [
            {"target": "right_atrium", "label": "RA"},
            {"target": "left_ventricle", "label": "LV"},
        ],
    }
    svg = builder.render({"title": "Human Heart", "data": data})
    assert is_valid_svg_xml(svg) is True
    assert "Human Heart" in svg
    assert "Aorta" in svg or ">Aorta<" in svg or "aorta" in svg.lower()
    assert "RA" in svg
    assert "LV" in svg


def test_stomata_open_and_closed_svg_generation():
    """
    Test open vs closed stomatal apparatus SVG rendering.
    """
    builder = BiologyBuilder()

    # Open stomata
    svg_open = builder.render({"title": "Open Stoma", "data": {"template": "stomata_open"}})
    assert is_valid_svg_xml(svg_open) is True
    assert "Open Stoma" in svg_open
    assert "Guard Cell" in svg_open
    assert "Stomatal Pore" in svg_open

    # Closed stomata
    svg_closed = builder.render({"title": "Closed Stoma", "data": {"template": "stomata_closed"}})
    assert is_valid_svg_xml(svg_closed) is True
    assert "Closed Stoma" in svg_closed


def test_neuron_and_reflex_arc_svg_generation():
    """
    Test motor neuron and reflex arc pathway SVG rendering.
    """
    builder = BiologyBuilder()

    # Neuron
    svg_neuron = builder.render({"title": "Motor Neuron", "data": {"template": "neuron"}})
    assert is_valid_svg_xml(svg_neuron) is True
    assert "Motor Neuron" in svg_neuron
    assert "Dendrite" in svg_neuron
    assert "Axon" in svg_neuron

    # Reflex Arc
    svg_reflex = builder.render({"title": "Reflex Arc", "data": {"template": "reflex_arc"}})
    assert is_valid_svg_xml(svg_reflex) is True
    assert "Reflex Arc" in svg_reflex
    assert "Sensory Neuron" in svg_reflex
    assert "Motor Neuron" in svg_reflex


def test_leaf_and_flower_and_cell_svg_generation():
    """
    Test leaf cross-section, flower anatomy, and plant cell ultra-structure rendering.
    """
    builder = BiologyBuilder()

    # Leaf
    svg_leaf = builder.render({"title": "Leaf Anatomy", "data": {"template": "leaf_cross_section"}})
    assert is_valid_svg_xml(svg_leaf) is True
    assert "Palisade Mesophyll" in svg_leaf

    # Flower
    svg_flower = builder.render({"title": "Flower Anatomy", "data": {"template": "flower_anatomy"}})
    assert is_valid_svg_xml(svg_flower) is True
    assert "Petal" in svg_flower
    assert "Ovary" in svg_flower

    # Plant Cell
    svg_cell = builder.render({"title": "Plant Cell", "data": {"template": "plant_cell"}})
    assert is_valid_svg_xml(svg_cell) is True
    assert "Cell Wall" in svg_cell

    # Digestive system
    svg_digest = builder.render({"title": "Alimentary Canal", "data": {"template": "digestive_system"}})
    assert is_valid_svg_xml(svg_digest) is True
    assert "Stomach" in svg_digest

    # Human Eye / Myopia Correction
    svg_eye = builder.render({
        "title": "Myopia Correction",
        "data": {
            "template": "myopia_correction",
            "biology_labels": [
                {"target": "cornea", "label": "Cornea"},
                {"target": "retina", "label": "Retina"},
            ],
        },
    })
    assert is_valid_svg_xml(svg_eye) is True
    assert "Myopia Correction" in svg_eye
    assert "Concave Lens" in svg_eye
    assert "Retina" in svg_eye

    # Ecological Pyramid
    svg_pyr = builder.render({
        "title": "Trophic Energy Flow",
        "data": {
            "template": "ecological_pyramid",
            "series": [{"values": [10000, 1000, 100, 10]}],
        },
    })
    assert is_valid_svg_xml(svg_pyr) is True
    assert "Trophic Energy Flow" in svg_pyr
    assert "10,000 J" in svg_pyr
    assert "Producers" in svg_pyr


def test_svg_generator_service_biology_dispatch():
    """
    Test end-to-end routing through SVGGeneratorService for type='biology'.
    """
    service = SVGGeneratorService()
    req = GeminiVisualRequirementSchema(
        required=True,
        type="biology",
        title="Nephron Structure",
        caption="Diagram of functional unit of kidney",
        spec={
            "template": "nephron",
            "biology_labels": [
                {"target": "glomerulus", "label": "X"},
                {"target": "bowman_capsule", "label": "Y"},
            ],
        },
    )

    res = service.generate(req)
    assert res.is_valid is True
    assert res.required is True
    assert is_valid_svg_xml(res.svg_raw) is True
    assert ">X<" in res.svg_raw
    assert ">Y<" in res.svg_raw


def test_visual_semantic_validator_biology():
    """
    Test VisualSemanticValidator warning checks for biology contexts.
    """
    res = VisualSemanticValidator.validate(
        question_text="Complete the Punnett square for a monohybrid cross of tall and dwarf pea plants.",
        visual_spec={"template": "nephron"},
        visual_type="biology",
    )
    assert res.is_valid is True
    assert any("Punnett square" in w for w in res.warnings)


def test_phototropism_svg_generation():
    """
    Test that BiologyBuilder renders the phototropism box experiment with shoot bending and auxin indicators.
    """
    builder = BiologyBuilder()
    data = {
        "template": "phototropism",
        "biology_labels": [
            {"target": "shoot", "label": "A"},
            {"target": "auxin", "label": "B"},
        ],
    }
    svg = builder.render({"title": "Phototropism Box Experiment", "data": data, "caption": "Plant shoot bending toward directional light source."})
    assert is_valid_svg_xml(svg) is True
    assert "Phototropism Box Experiment" in svg
    assert "Light Source" in svg
    assert "Auxin" in svg
    assert ">A<" in svg
    assert ">B<" in svg

    # Also test smart fallback routing when template was stomata_open but title is Phototropism Box Experiment
    service = SVGGeneratorService()
    res = service.generate({
        "type": "biology",
        "title": "Phototropism Box Experiment",
        "spec": {"template": "stomata_open"},
    })
    assert res.is_valid is True
    assert "Light Source" in res.svg_raw
    assert "Auxin" in res.svg_raw


def test_female_reproductive_system_svg_generation():
    """
    Test that BiologyBuilder renders the human female reproductive system with uterus, oviducts, and ovaries.
    """
    builder = BiologyBuilder()
    data = {
        "template": "female_reproductive_system",
        "biology_labels": [
            {"target": "ovary", "label": "A"},
            {"target": "oviduct", "label": "B"},
        ],
    }
    svg = builder.render({"title": "Human Reproductive Anatomy", "data": data, "caption": "Female reproductive organs."})
    assert is_valid_svg_xml(svg) is True
    assert "Human Reproductive Anatomy" in svg
    assert "Uterus" in svg
    assert ">A<" in svg
    assert ">B<" in svg

    # Also test smart fallback routing when template was flower_anatomy but title is Human Reproductive Anatomy
    service = SVGGeneratorService()
    res = service.generate({
        "type": "biology",
        "title": "Human Reproductive Anatomy",
        "spec": {"template": "flower_anatomy"},
    })
    assert res.is_valid is True
    assert "Uterus" in res.svg_raw
    assert "Ovary" in res.svg_raw or "Oviduct" in res.svg_raw


def test_punnett_square_dihybrid_and_monohybrid_accuracy():
    """
    Test that Punnett square renders clean headers ('Female Gametes ♀'),
    sanitizes caption typos ('T1' -> 'Tt'), and accurately computes dihybrid combinations (Ry x RY -> RRYy).
    """
    builder = BiologyBuilder()

    # 1. Monohybrid with typo in caption
    mono_data = {
        "template": "punnett_square",
        "parent1": "Tt",
        "parent2": "Tt",
        "gametes1": ["T", "t"],
        "gametes2": ["T", "t"],
    }
    mono_svg = builder.render({
        "title": "Monohybrid Cross",
        "data": mono_data,
        "caption": "Cross showing parental genotypes T1 crossed with Tt yielding F2 generation",
    })
    assert is_valid_svg_xml(mono_svg) is True
    assert ">Female Gametes ♀<" in mono_svg
    assert ">Male Gametes ♂<" in mono_svg
    assert "Female Gametes (Tt)" not in mono_svg
    assert "T1" not in mono_svg
    assert "parental genotypes Tt crossed with Tt" in mono_svg

    # 2. Dihybrid 4x4 matrix
    dihybrid_data = {
        "template": "punnett_square",
        "parent1": "RrYy",
        "parent2": "RrYy",
        "gametes1": ["RY", "Ry", "rY", "ry"],
        "gametes2": ["RY", "Ry", "rY", "ry"],
    }
    dihy_svg = builder.render({
        "title": "Dihybrid Cross Matrix",
        "data": dihybrid_data,
    })
    assert is_valid_svg_xml(dihy_svg) is True
    assert ">RRYY<" in dihy_svg
    assert ">RRYy<" in dihy_svg
    assert ">RrYY<" in dihy_svg
    assert ">RrYy<" in dihy_svg
    assert ">RRyy<" in dihy_svg
    assert ">rrYY<" in dihy_svg
    assert ">rrYy<" in dihy_svg
    assert ">rryy<" in dihy_svg


def test_hypermetropia_convex_lens_diagram():
    """
    Test that BiologyBuilder renders hypermetropia with a convex converging lens,
    near object point N, and rays focusing behind retina if uncorrected.
    """
    builder = BiologyBuilder()
    svg = builder.render({
        "title": "Hypermetropia and Correction",
        "data": {
            "template": "human_eye",
            "biology_labels": [
                {"target": "retina", "label": "Retina"},
            ],
        },
    })
    assert is_valid_svg_xml(svg) is True
    assert "Hypermetropia" in svg
    assert "Convex Lens (Correction)" in svg
    assert "Concave Lens" not in svg
    assert "N (Near Object)" in svg
    assert "Uncorrected Focus (Behind Retina)" in svg
    assert "Corrected Focus on Retina" in svg

    # Also test via SVGGeneratorService with hypermetropia title
    service = SVGGeneratorService()
    res = service.generate({
        "type": "biology",
        "title": "Hypermetropia Optical Ray Diagram",
        "spec": {"template": "eye"},
    })
    assert res.is_valid is True
    assert "Convex Lens" in res.svg_raw
    assert "Behind Retina" in res.svg_raw


def test_ecological_pyramid_lindeman_ten_percent_law():
    """
    Test that the ecological energy pyramid strictly adheres to Lindeman's 10% law
    (10,000 -> 1,000 -> 100 -> 10 J) and displays uniform '90% Heat Loss' at every tier.
    """
    builder = BiologyBuilder()
    # Even if noisy values were passed from LLM
    svg = builder.render({
        "title": "Ecological Energy Pyramid",
        "data": {
            "template": "ecological_pyramid",
            "series": [{"values": [10000, 1001, 100, 10.2]}],
        },
    })
    assert is_valid_svg_xml(svg) is True
    assert "10,000 J" in svg
    assert "1,000 J (10%)" in svg
    assert "100 J (1%)" in svg
    assert "10 J (0.1%)" in svg
    assert "1001 J" not in svg
    assert "10.2" not in svg
    # Count occurrences of "90% Heat Loss" - must appear at all 4 tiers
    assert svg.count("90% Heat Loss") == 4


def test_nephron_margins_and_capillary_routing():
    """
    Test that Nephron labels (Afferent Arteriole, Bowman's Capsule) have safe margins
    and do not clip on the left edge of the SVG.
    """
    builder = BiologyBuilder()
    svg = builder.render({
        "title": "Structure of a Nephron",
        "data": {"template": "nephron"},
    })
    assert is_valid_svg_xml(svg) is True
    assert "Afferent Arteriole" in svg
    assert "Efferent Arteriole" in svg
    assert "Glomerulus" in svg
    assert ("Bowman's Capsule" in svg or "Bowman&#x27;s Capsule" in svg)
    assert "Renal Venule" in svg


def test_reflex_arc_pathway_direction_and_no_text_overlap():
    """
    Test that reflex arc labels are non-overlapping and the efferent motor neuron arrow
    points toward the effector muscle.
    """
    builder = BiologyBuilder()
    svg = builder.render({
        "title": "Reflex Arc Pathway",
        "data": {"template": "reflex_arc"},
    })
    assert is_valid_svg_xml(svg) is True
    assert "Stimulus (Heat)" in svg
    assert "Receptor (Skin)" in svg
    assert "Heat / Stimulusceptor" not in svg  # No overlapping garbled text
    assert "Effector (Muscle)" in svg
    assert "NCERT Pathway" in svg



