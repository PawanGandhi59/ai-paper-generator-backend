# Gemini Visual-Spec Contract & Architecture Design

## 1. Purpose & Overview
This document defines the formal, machine-readable contract for AI-driven visual generation within the AI Paper Generator backend. 

The contract governs how Google Gemini declares that an examination question requires an accompanying visual illustration (`diagram`, `chart`, `geometry`, `circuit`, or `graph`) and provides structured semantic data that the backend validates and converts into deterministic, scalable SVG markup via `SVGGeneratorService`.

```
+-------------------------------------------------------------+
|                       Google Gemini                         |
|     (Generates Question JSON + Structured Visual Contract)   |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|               Visual Specification Validator                |
|      (Pydantic Type Validation + Semantic Integrity Checks) |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                    SVGGeneratorService                      |
|                 (Central Global Entry Point)                |
+------------------------------+------------------------------+
                               |
       +-----------------------+-----------------------+
       |           |           |           |           |
       v           v           v           v           v
+------------+------------+------------+------------+------------+
| SVGRenderer| SVGRenderer|  Geometry  |  Circuit   |   Graph    |
| (Diagram)  |  (Chart)   |  Builder   |  Builder   |  Builder   |
+------------+------------+------------+------------+------------+
       |           |           |           |           |
       +-----------------------+-----------------------+
                               |
                               v
+-------------------------------------------------------------+
|                  Clean, Deterministic SVG                   |
+-------------------------------------------------------------+
```

---

## 2. Core Architectural Principles

1. **Gemini Describes Intent; Backend Calculates & Renders:**
   Gemini outputs pure semantic structured data. The backend builder performs coordinate mapping, viewBox calculations, bounding box math, label offsets, arrow styling, and XML escaping.

2. **No Arbitrary Raw SVG Generation from LLM:**
   Gemini is **strictly prohibited** from returning raw SVG XML strings. `raw_svg` is not part of the Gemini-facing contract (`GeminiVisualType = Literal["diagram", "chart", "geometry", "circuit", "graph"]`).

3. **Single Global Entry Point:**
   All visual requests pass exclusively through `SVGGeneratorService.generate(spec)`.

4. **Visuals Only When Genuinely Required:**
   Gemini requests a visual (`required=true`) **only when the question genuinely depends on a visual illustration**. For conceptual or non-visual questions, `visual` is `null` or omitted.

5. **Strict Semantic Validation (No Silent Swallowing of Broken Visuals):**
   When `required=true`, the visual schema must strictly validate against type-specific semantic rules. Malformed or invalid visual specs raise clear validation errors rather than being silently ignored.

---

## 3. Canonical Visual Types

The 5 approved visual types exposed to Gemini are:

| Visual Type | Target Use Cases | Primary Builder |
| :--- | :--- | :--- |
| `diagram` | Flowcharts, classification trees, sequence diagrams, process hierarchies | `SVGRenderer` |
| `chart` | Bar charts, line graphs, pie charts, histograms, category comparisons | `SVGRenderer` |
| `geometry` | Triangles, polygons, circles, angles, vectors, rays, coordinate shapes | `GeometryBuilder` |
| `circuit` | Series/parallel circuits, schematic components, instruments, switches | `CircuitBuilder` |
| `graph` | 2D Cartesian plots $f(x)$, functions ($\sin, \cos, x^2$), coordinate points | `GraphBuilder` |

---

## 4. Question Visual Contract Schema

```json
{
  "question_text": "In the given circuit, calculate the total current flowing from the battery.",
  "question_type": "NUMERICAL",
  "marks": 3,
  "difficulty": "MEDIUM",
  "is_numerical": true,
  "visual": {
    "required": true,
    "type": "circuit",
    "title": "DC Series Circuit",
    "caption": "A 12 V battery connected to a 6 ohm resistor",
    "spec": {
      "components": [
        {"id": "V1", "type": "battery", "label": "12 V"},
        {"id": "R1", "type": "resistor", "label": "6 Ω"}
      ],
      "connections": [
        {"from": "V1", "to": "R1", "show_current": true, "label": "I = 2A"},
        {"from": "R1", "to": "V1"}
      ]
    }
  },
  "correct_answer": "2 A",
  "solution_explanation": "Using Ohm's Law: I = V / R = 12 V / 6 Ω = 2 A."
}
```

If no visual is needed, `visual` is omitted or set to `null`.

---

## 5. Semantic Validation Rules (`validate_visual_spec_semantics`)

1. **`diagram`:**
   - Node IDs must be unique.
   - All edge `from` and `to` endpoints must reference existing node IDs.
2. **`chart`:**
   - Categories list must have at least 1 item.
   - For each series, value array length must match category count.
3. **`geometry`:**
   - Point IDs must be unique.
   - Segments cannot have identical start and end points (`from != to`).
   - If points are defined, all segment endpoints, polygon vertices, and circle centers must reference valid point IDs.
   - Polygons must have at least 3 vertices.
   - Circle radius must be strictly positive ($r > 0$).
4. **`circuit`:**
   - Component IDs and junction IDs must be unique.
   - Component types must be valid (`ComponentType`).
   - Wires cannot connect a component to itself.
   - Connections must reference valid component IDs or junction IDs.
5. **`graph`:**
   - $x_{min} < x_{max}$ and $y_{min} < y_{max}$.
   - All function expressions are evaluated via AST safety validation (`validate_math_expression_safety`). Unsafe code (`eval`, `__import__`, attribute lookups, disallowed operators) is rejected.

---

## 6. Internal-Choice Compatibility

For internal-choice questions ($Q4a \text{ OR } Q4b$), each alternative is represented as an independent `GeminiGeneratedQuestionSchema` item in the question array.
- Alternative (a) can carry a `circuit` visual requirement.
- Alternative (b) can carry a `geometry` visual requirement (or no visual at all).
- Each alternative maintains complete independence in its visual specification.
