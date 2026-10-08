import xml.etree.ElementTree as ET
import pytest

from app.services.visuals.builders.science_experiment_builder import ScienceExperimentBuilder
from app.services.visuals.svg_generator_service import SVGGeneratorService
from app.services.visuals.svg_renderer import VisualSpec


def test_glass_slab_refraction_svg_markup():
    spec = VisualSpec(
        id="v_slab",
        type="experiment",
        title="Refraction of Light through a Rectangular Glass Slab",
        caption="CBSE Class 10 Light Refraction & Lateral Displacement",
        data={"template": "glass_slab_refraction"},
    )
    svg = ScienceExperimentBuilder.render(spec)
    assert svg.strip().startswith("<svg")
    assert svg.strip().endswith("</svg>")
    
    # Must parse as valid XML
    root = ET.fromstring(svg)
    assert "svg" in root.tag.lower()
    
    # Verify core optical features
    assert "Incident Ray" in svg
    assert "Refracted Ray" in svg
    assert "Emergent Ray" in svg
    assert "Lateral Displacement" in svg
    assert "Angle of Incidence" in svg or "Angle of emergence" in svg or "Glass Slab" in svg


def test_magnetic_field_wire_svg_markup():
    spec = VisualSpec(
        id="v_mag",
        type="experiment",
        title="Magnetic Field around a Straight Current-Carrying Conductor",
        caption="Right-Hand Thumb Rule Demonstration",
        data={"template": "magnetic_field_wire"},
    )
    svg = ScienceExperimentBuilder.render(spec)
    assert svg.strip().startswith("<svg")
    assert svg.strip().endswith("</svg>")
    
    # Must parse as valid XML
    root = ET.fromstring(svg)
    assert "svg" in root.tag.lower()
    
    # Verify electromagnetic components
    assert "Concentric Magnetic Field Lines" in svg
    assert "Copper Conductor" in svg
    assert "Cardboard" in svg
    assert "Current Flow" in svg or "Current (I)" in svg


def test_water_electrolysis_svg_markup():
    spec = VisualSpec(
        id="v_electro",
        type="experiment",
        title="Electrolysis of Water Apparatus",
        caption="Decomposition of water into H2 and O2 in 2:1 volume ratio",
        data={"template": "water_electrolysis"},
    )
    svg = ScienceExperimentBuilder.render(spec)
    assert svg.strip().startswith("<svg")
    assert svg.strip().endswith("</svg>")
    
    # Must parse as valid XML
    root = ET.fromstring(svg)
    assert "svg" in root.tag.lower()
    
    # Verify chemical apparatus features
    assert "Cathode" in svg
    assert "Anode" in svg
    assert "6V DC Battery" in svg
    assert "Plastic Mug" in svg
    assert "Hydrogen" in svg or "H₂" in svg
    assert "Oxygen" in svg or "O₂" in svg


def test_svg_generator_service_experiment_dispatch():
    service = SVGGeneratorService()
    
    # 1. Direct experiment type
    res = service.generate({
        "type": "experiment",
        "title": "Refraction of Light through a Rectangular Glass Slab",
        "spec": {"template": "glass_slab_refraction"},
    })
    assert res.is_valid is True
    assert "Lateral Displacement" in res.svg_raw

    # 2. Smart fallback routing when type is 'diagram' but title/template is experiment
    res2 = service.generate({
        "type": "diagram",
        "title": "Magnetic Field lines around a straight conductor",
        "spec": {"template": "magnetic_field_wire"},
    })
    assert res2.is_valid is True
    assert "Concentric Magnetic Field Lines" in res2.svg_raw

    # 3. Smart fallback routing for electrolysis
    res3 = service.generate({
        "type": "diagram",
        "title": "Electrolysis of Water Experimental Setup",
        "spec": {"template": "water_electrolysis"},
    })
    assert res3.is_valid is True
    assert "Cathode" in res3.svg_raw


def test_glass_prism_svg_markup():
    spec = VisualSpec(
        id="v_prism",
        type="experiment",
        title="Glass Slab Refraction and Dispersion",
        caption="Refraction through optical media.",
        data={"template": "glass_prism"},
    )
    svg = ScienceExperimentBuilder.render(spec)
    assert svg.strip().startswith("<svg")
    assert svg.strip().endswith("</svg>")

    # Must parse as valid XML
    root = ET.fromstring(svg)
    assert "svg" in root.tag.lower()

    # Core optical prism features
    assert "Triangular Glass Prism" in svg
    assert "Incident Ray" in svg
    assert "Refracted Ray" in svg
    assert "Emergent Ray" in svg
    assert "Angle of Deviation" in svg
    assert "∠D" in svg

    # Also test smart fallback routing when title has 'Dispersion' or 'Prism'
    service = SVGGeneratorService()
    res = service.generate({
        "type": "experiment",
        "title": "Glass Prism Refraction and Dispersion",
        "spec": {"template": "glass_slab_refraction"},  # Mismatched template
    })
    assert res.is_valid is True
    assert "Angle of Deviation" in res.svg_raw

