# Phase 3D Pre-Implementation Compatibility Audit

## 1. Executive Summary & Verdict

**Overall Compatibility Result: PASS WITH REQUIRED CHANGES**

The existing deterministic visual architecture (`SVGGeneratorService` + specialized builders) provides a solid foundation for rendering clean, scalable SVGs from structured data. However, our compatibility audit uncovered **4 specific schema-to-builder mismatches** that must be addressed in Phase 3D to ensure end-to-end reliability without breaking existing workflows or crashing paper generation.

---

## 2. Visual Type Compatibility Matrix

| Visual Type | Gemini Schema | Builder | Compatible? | Required Changes for Phase 3D |
| :--- | :--- | :--- | :--- | :--- |
| **`geometry`** | `GeometryData` (points with optional `x, y`, segments, polygons, angles, circles) | `GeometryBuilder` | **FAIL (without coordinates)** | In `GeometryBuilder`: Auto-synthesize coordinates when `p.x is None` or `p.y is None`, not only when `pid not in points_map`. Filter `None` values before computing bounding box. |
| **`circuit`** | `CircuitData` (components with optional `x, y`, connections, junctions) | `CircuitBuilder` | **PASS** | Fully compatible. `_ensure_component_positions` automatically synthesizes rectangular loop layout when coordinates are omitted. |
| **`graph`** | `GraphData` (`x_range`, `y_range`, `functions`, `points`, `segments`) | `GraphBuilder` | **PASS** | Fully compatible. AST `SafeExprEvaluator` evaluates function curves and bounds deterministically without `eval()`. |
| **`diagram`** | `DiagramData` (`nodes`, `edges`) | `SVGRenderer._render_diagram` | **PASS** | Fully compatible. Automatically lays out nodes horizontally/vertically with dynamic width/height and perimeter arrow routing. |
| **`chart`** | `ChartDataSpec` (`categories`, `series: List[ChartSeriesData]`, `format`) | `SVGRenderer._render_chart` | **PARTIAL (Fallback)** | Legacy `ChartData` expects flat `values: List[float]` instead of `series`. In Phase 3D, adapter must map `spec.series[0].values` into `values` for single-series charts or add multi-series bar rendering. |

---

## 3. Detailed Audit Findings & Gaps

### Gap 1: Geometry Coordinate Synthesis when `x` / `y` is `None`
- **Issue:** `GeometryPoint` allows `x: Optional[float] = None` and `y: Optional[float] = None` so Gemini can supply semantic point IDs without computing pixel coordinates.
- **Root Cause in Builder:** 
  1. In `GeometryBuilder.render()`, `points_map = {p.id: p for p in geom_data.points}`.
  2. `_ensure_point_coordinates()` checks `if pid not in points_map:`, so points that exist with `x=None` are skipped.
  3. `_compute_bounds()` evaluates `min(xs)` where `xs` contains `None`, raising `TypeError: '<' not supported between instances of 'NoneType' and 'NoneType'`.
- **Phase 3D Solution:**
  Update `GeometryBuilder._ensure_point_coordinates()` to check `p.x is None or p.y is None`, and filter `None` values in `_compute_bounds()`.

### Gap 2: Chart Data Format Mismatch (`series` vs flat `values`)
- **Issue:** Gemini's `ChartDataSpec` (Phase 3B schema) defines `categories: List[str]` and `series: List[ChartSeriesData]` where each series has `values: List[float]`.
- **Root Cause in Builder:**
  `SVGRenderer._render_chart()` unpacks `ChartData` expecting `values: List[float]` directly at top level. When passed `series`, `values` defaults to `[]`, causing `_render_chart()` to emit a fallback empty title box instead of rendering data bars.
- **Phase 3D Solution:**
  Add a lightweight adapter in `SVGGeneratorService` (or update `SVGRenderer._render_chart()`) to support both `series` and flat `values`.

### Gap 3: Payload Key Resolution in `SVGGeneratorService.generate()`
- **Issue:** In `SVGGeneratorService.generate(spec)`, when `spec` is a dictionary from `GeminiVisualRequirementSchema.model_dump()`, the payload key is `"spec"`:
  ```python
  {"required": True, "type": "circuit", "title": "...", "spec": {...}}
  ```
- **Root Cause in Service:**
  `SVGGeneratorService.generate()` looks up `spec.get("spec_data") or spec.get("data")`, but does **not** check `spec.get("spec")`. Consequently, `v_data` resolves to `{}`.
- **Phase 3D Solution:**
  Update payload extraction: `v_data = spec.get("spec") or spec.get("spec_data") or spec.get("data") or {}`. Also support `GeminiVisualRequirementSchema` directly as an accepted input type in `SVGGeneratorService.generate()`.

---

## 4. Validation vs Rendering Gaps

| Scenario | Schema Validation | SVG Rendering (Current) | Recommended Phase 3D Behavior |
| :--- | :--- | :--- | :--- |
| **Geometry with semantic points (no coordinates)** | **PASS** | **FAIL** (`TypeError`) | Fix coordinate synthesis so rendering **PASSES** deterministically. |
| **Chart with `series` list** | **PASS** | **PARTIAL** (Empty Fallback Box) | Add series adapter so bars render correctly. |
| **Circuit with auto-layout** | **PASS** | **PASS** | Keep as-is. |
| **Graph with safe math expression** | **PASS** | **PASS** | Keep as-is. |
| **Diagram with semantic nodes/edges** | **PASS** | **PASS** | Keep as-is. |

---

## 5. Failure-Handling & Non-Destructive Fallback Strategy

When a question genuinely requires a visual (`visual.required: true`):

```
+-------------------------------------------------------------+
|               Gemini Output Question JSON                   |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|             Pydantic Schema & Semantic Validation           |
|            (validate_visual_spec_semantics)                 |
+------------------------------+------------------------------+
        |                                             |
        | (Valid Spec)                                | (Malformed Spec / Unsafe AST)
        v                                             v
+-------------------------------+             +-------------------------------+
|  SVGGeneratorService.generate |             | Log Warning                   |
+---------------+---------------+             | Set visual_valid = False      |
        |               |                     | Preserve Question & Answers   |
(Valid SVG)    (Render Error)                 +---------------+---------------+
        |               |                                     |
        v               v                                     |
[visual_svg = SVG]  [visual_svg = None, visual_valid = False] |
        |               |                                     |
        +---------------+-------------------------------------+
                        |
                        v
+-------------------------------------------------------------+
|       Persist Question to Database / Return in Response     |
+-------------------------------------------------------------+
```

### Key Principles:
1. **Never Crash the Complete Paper:** If an individual question's visual rendering fails, the question text, MCQ options, correct answer, expected answer, and solution explanation **must be preserved**.
2. **Explicit Validity Flag:** `GeneratedPaperQuestion` / `PaperQuestionResponse` will record `visual_required: bool` and `visual_svg: Optional[str]`, allowing the frontend to know whether the visual is ready for display.

---

## 6. SVG Validity Verification

`SVGGeneratorService` currently performs basic string presence checks:
```python
is_valid_markup = bool(svg_markup and "<svg" in svg_markup and "</svg>" in svg_markup)
```
For Phase 3D, we recommend strengthening this check with lightweight XML validation:
- Root tag is `<svg>`
- `viewBox` attribute is present
- Closing `</svg>` tag is present
- No unhandled runtime exceptions during XML assembly

---

## 7. Phase 3D Readiness & Required Modifications

Phase 3D can proceed safely once the following 4 targeted modifications are implemented in the visual service layer:

1. **`app/services/visuals/svg_generator_service.py`:**
   - Accept `GeminiVisualRequirementSchema` in `.generate()`.
   - Resolve `spec.get("spec")` alongside `spec_data` and `data`.
2. **`app/services/visuals/builders/geometry_builder.py`:**
   - Enhance `_ensure_point_coordinates()` and `_compute_bounds()` to safely auto-synthesize coordinates when `p.x is None`.
3. **`app/services/visuals/svg_renderer.py`:**
   - Support `series: List[ChartSeriesData]` in `_render_chart()`.
4. **`app/services/paper/paper_generator_service.py`:**
   - Wire `SVGGeneratorService.generate()` into paper generation pipeline for questions where `visual` is present.
