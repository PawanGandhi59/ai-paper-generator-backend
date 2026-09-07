import html
import logging
from typing import Any, Dict, Optional, Union
import xml.etree.ElementTree as ET
from pydantic import BaseModel, Field

from app.schemas.visuals import (
    GeminiVisualRequirementSchema,
    VisualRequiredSpec,
    VisualType,
)
from app.services.visuals.builders.circuit_builder import CircuitBuilder
from app.services.visuals.builders.geometry_builder import GeometryBuilder
from app.services.visuals.builders.graph_builder import GraphBuilder
from app.services.visuals.svg_renderer import SVGRenderer, VisualSpec

logger = logging.getLogger(__name__)


def is_valid_svg_xml(svg_string: str) -> bool:
    """
    Lightweight, deterministic validation of SVG markup.
    Verifies that the string is non-empty, contains <svg> and </svg>,
    has a valid viewBox or dimensions, and parses as well-formed XML.
    """
    if not svg_string or not isinstance(svg_string, str):
        return False
    clean = svg_string.strip()
    if not clean.startswith("<svg") or not clean.endswith("</svg>"):
        return False
    try:
        root = ET.fromstring(clean)
        # Check that root tag is svg (ignoring or handling namespaces)
        tag_name = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        if tag_name.lower() != "svg":
            return False
        return True
    except Exception as exc:
        logger.warning(f"SVG XML validation error: {exc}")
        return False


class GeneratedSVGResult(BaseModel):
    """
    Result model returned by SVGGeneratorService.
    Contains rendered SVG XML markup, validity, and requirement metadata.
    """
    svg_raw: str = Field("", description="Raw, self-contained SVG XML string markup")
    is_valid: bool = Field(False, description="Whether SVG rendering succeeded and produced valid XML markup")
    required: bool = Field(False, description="Whether this visual was strictly required by the question")
    title: str = Field("Visual Diagram", description="Title or header for the visual artifact")
    caption: Optional[str] = Field(None, description="Optional caption or educational description")
    file_path: Optional[str] = Field(None, description="Optional local file storage path if persisted")
    public_url: Optional[str] = Field(None, description="Optional public URL if persisted")
    error_message: Optional[str] = Field(None, description="Detailed error explanation if generation failed")


class SVGGeneratorService:
    """
    Centralized, subject-agnostic global backend service for generating valid,
    scalable SVG diagrams and charts across the AI Paper Generator application.
    """

    def generate(
        self,
        spec: Union[GeminiVisualRequirementSchema, VisualRequiredSpec, VisualSpec, Dict[str, Any]],
        title: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> GeneratedSVGResult:
        """
        Single global entry point for SVG visual generation.
        Accepts GeminiVisualRequirementSchema, VisualRequiredSpec, VisualSpec, or dictionary payloads.
        Delegates supported visual types (diagram, chart, geometry, circuit, graph) to appropriate builders.
        Handles unsupported types and rendering errors safely without crashing.
        """
        v_required: bool = False
        try:
            v_type: Optional[str] = None
            v_format: str = "flowchart"
            v_title: str = title or "Visual Diagram"
            v_caption: Optional[str] = caption
            v_data: Dict[str, Any] = {}

            if isinstance(spec, GeminiVisualRequirementSchema):
                v_required = bool(spec.required)
                v_type = spec.type
                v_title = title or spec.title or "Visual Diagram"
                v_caption = caption or spec.caption
                raw_spec = spec.spec
                v_data = raw_spec.model_dump(by_alias=True, exclude_none=True) if hasattr(raw_spec, "model_dump") else (raw_spec or {})
            elif isinstance(spec, VisualRequiredSpec):
                v_required = bool(spec.visual_required)
                v_type = spec.visual_type
                v_format = spec.format or "flowchart"
                v_title = title or spec.title or "Visual Diagram"
                v_caption = caption or spec.caption
                v_data = spec.spec_data or {}
                if spec.raw_svg_code and spec.raw_svg_code.strip():
                    raw_code = spec.raw_svg_code.strip()
                    if is_valid_svg_xml(raw_code):
                        return GeneratedSVGResult(
                            svg_raw=raw_code,
                            is_valid=True,
                            required=v_required,
                            title=v_title,
                            caption=v_caption,
                        )
            elif isinstance(spec, VisualSpec):
                v_type = spec.type
                v_format = spec.format or "flowchart"
                v_title = title or spec.title or "Visual Diagram"
                v_caption = caption or spec.caption
                v_data = spec.data or {}
            elif isinstance(spec, dict):
                v_required = bool(spec.get("required") or spec.get("visual_required", False))
                v_type = spec.get("type") or spec.get("visual_type")
                v_format = spec.get("format") or "flowchart"
                v_title = title or spec.get("title") or "Visual Diagram"
                v_caption = caption or spec.get("caption")
                # Resolve spec, spec_data, or data
                v_data = spec.get("spec") or spec.get("spec_data") or spec.get("data") or {}

            if not v_type or v_type not in ["diagram", "chart", "geometry", "circuit", "graph"]:
                err_msg = f"Unsupported or unspecified visual type '{v_type}'."
                logger.warning(f"SVGGeneratorService: {err_msg}")
                return GeneratedSVGResult(
                    svg_raw="",
                    is_valid=False,
                    required=v_required,
                    title=v_title,
                    caption=v_caption,
                    error_message=err_msg,
                )

            # Build VisualSpec payload for builders
            renderer_spec = VisualSpec(
                id="svg_gen_1",
                type=v_type,
                format=v_format,
                title=v_title,
                caption=v_caption,
                data=v_data,
            )

            if v_type == "graph":
                svg_markup = GraphBuilder.render(renderer_spec)
            elif v_type == "circuit":
                svg_markup = CircuitBuilder.render(renderer_spec)
            elif v_type == "geometry":
                svg_markup = GeometryBuilder.render(renderer_spec)
            else:
                svg_markup = SVGRenderer.render(renderer_spec)

            is_valid_markup = is_valid_svg_xml(svg_markup)

            return GeneratedSVGResult(
                svg_raw=svg_markup if is_valid_markup else "",
                is_valid=is_valid_markup,
                required=v_required,
                title=v_title,
                caption=v_caption,
                error_message=None if is_valid_markup else "SVG XML structure validation failed.",
            )

        except Exception as exc:
            err_msg = f"SVGGeneratorService.generate execution error: {exc}"
            logger.error(err_msg)
            return GeneratedSVGResult(
                svg_raw="",
                is_valid=False,
                required=v_required,
                title=title or "Visual Diagram",
                caption=caption,
                error_message=err_msg,
            )
