# 📘 AI Educational Tutor API — Frontend Integration Guide

This guide details how Flutter and Web frontend developers can integrate the **AI Educational Tutor RAG Service** and render **Structured Visual Responses** (Mermaid Diagrams, JSON Charts, and Authenticated Generated PNG Images).

---

## 🚀 1. Endpoint Overview

| Endpoint | Method | Auth Required | Description |
| :--- | :--- | :--- | :--- |
| `/api/v1/ai/query` | `POST` | `Bearer <JWT>` | RAG Educational Tutor query returning Markdown answer, structured visuals, and source citations. |
| `/api/v1/ai/visuals/{visual_id}` | `GET` | `Bearer <JWT>` | Authenticated binary file stream (`image/png`) for generated educational images. |

---

## 📡 2. API Specifications

### 2.1 `POST /api/v1/ai/query`

#### Request Headers
```http
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
```

#### Request Body Schema (`AIQueryRequest`)
```json
{
  "query": "Explain with a clear text diagram or classification chart: how are the different birds near Jaggu's house categorized by their colors and features?",
  "workspace_id": "51168143-ef07-412f-9ba5-ce946bbbdd65",
  "book_id": "6d210a6e-ecbd-4ce9-8198-da6904f4e8cd",
  "chapter_id": "7430b450-f4c4-4d56-b1d3-c409485e9ba3",
  "document_id": "5da58ee1-247d-4462-8f70-bfd9b9e3d9d9",
  "top_k": 5
}
```

- `query` *(string, required)*: Student question or request.
- `workspace_id` *(UUID, required)*: Active workspace ID for tenant security isolation.
- `book_id` *(UUID, optional)*: Filter context retrieval to a specific book.
- `chapter_id` *(UUID, optional)*: Filter context retrieval to a specific chapter.
- `document_id` *(UUID, optional)*: Filter context retrieval to a specific document.
- `top_k` *(integer, optional, default: 5)*: Number of document chunks to retrieve (1–20).

---

#### Response Body Schema (`AIQueryResponse`)

```json
{
  "answer": "The birds near Jaggu's house can be categorized based on their color patterns and features:\n\n1. **Black**: Crow\n2. **Grey**: Pigeon\n3. **Small / Brown**: Sparrow",
  "visuals": [
    {
      "id": "visual_1",
      "type": "diagram",
      "format": "mermaid",
      "title": "Birds Classification Near Jaggu's House",
      "content": "graph TD\n  Birds[Birds Near House] --> Crow[Crow: Black]\n  Birds --> Pigeon[Pigeon: Grey]\n  Birds --> Sparrow[Sparrow: Small/Brown]",
      "caption": "Classification tree based on bird color and features"
    }
  ],
  "model_used": "gemini-3.1-flash-image",
  "sources": [
    {
      "chunk_id": "8de93dc9-8ba0-4105-a5d2-78bc8d727ccd",
      "document_id": "5da58ee1-247d-4462-8f70-bfd9b9e3d9d9",
      "page_number": 6,
      "chapter_id": "7430b450-f4c4-4d56-b1d3-c409485e9ba3",
      "distance": 0.2831
    }
  ]
}
```

---

## 🎨 3. Visual Artifact Rendering Logic

The backend categorizes visual artifacts into three distinct types inside `visuals[]`:

### 3.1 Diagrams (`type: "diagram"`, `format: "mermaid"`)
- `content` contains standard **Mermaid.js** code (`graph TD`, `sequenceDiagram`, `flowchart LR`, etc.).
- **Flutter**: Use `flutter_mermaid` package or render in a light WebView via `webview_flutter`.
- **Web / React**: Use `mermaid.js` library (`mermaid.render()`).

```javascript
// Web/React Mermaid Example
import mermaid from 'mermaid';

function RenderDiagram({ code }) {
  useEffect(() => {
    mermaid.contentLoaded();
  }, [code]);

  return <div className="mermaid">{code}</div>;
}
```

---

### 3.2 Charts (`type: "chart"`, `format: "json"`)
- `content` contains a serialized JSON string representing data points.
- **Flutter**: Parse `content` string with `jsonDecode()` and render using `fl_chart`.
- **Web / React**: Parse JSON string and render using `Recharts` or `Chart.js`.

```json
{
  "type": "chart",
  "format": "json",
  "title": "Bird Population Comparison",
  "content": "{\"labels\": [\"Crow\", \"Pigeon\", \"Sparrow\"], \"values\": [12, 8, 15]}",
  "caption": "Distribution of birds seen in chapter 1"
}
```

---

### 3.3 Educational Images (`type: "image"`, `format: "url"`)
- `content` contains a relative API URL path: `/api/v1/ai/visuals/{visual_id}`.
- **SECURITY REQUIRED**: The image endpoint requires `Bearer <token>` authentication. Direct `<img src="...">` without auth headers will fail with `401 Unauthorized`.
- **IDOR Protection**: The server checks that the requesting user owns the workspace where the image was generated, returning `404 Not Found` for unauthorized attempts.

#### Loading Authenticated Image in Flutter:

```dart
import 'package:flutter/material.dart';

Widget buildAuthenticatedImage(String imagePath, String jwtToken) {
  final fullUrl = 'https://api.yourdomain.com$imagePath';
  
  return Image.network(
    fullUrl,
    headers: {'Authorization': 'Bearer $jwtToken'},
    loadingBuilder: (context, child, progress) {
      if (progress == null) return child;
      return CircularProgressIndicator();
    },
    errorBuilder: (context, error, stackTrace) =>
        Icon(Icons.broken_image, color: Colors.grey),
  );
}
```

---

## 📱 4. Flutter Dart Data Models

```dart
class VisualItem {
  final String id;
  final String type; // "diagram", "chart", "image"
  final String format; // "mermaid", "json", "url"
  final String title;
  final String content;
  final String? caption;

  VisualItem({
    required this.id,
    required this.type,
    required this.format,
    required this.title,
    required this.content,
    this.caption,
  });

  factory VisualItem.fromJson(Map<String, dynamic> json) {
    return VisualItem(
      id: json['id'] as String,
      type: json['type'] as String,
      format: json['format'] as String,
      title: json['title'] as String,
      content: json['content'] as String,
      caption: json['caption'] as String?,
    );
  }
}

class AIQueryResponse {
  final String answer;
  final List<VisualItem> visuals;
  final String modelUsed;
  final List<dynamic> sources;

  AIQueryResponse({
    required this.answer,
    required this.visuals,
    required this.modelUsed,
    required this.sources,
  });

  factory AIQueryResponse.fromJson(Map<String, dynamic> json) {
    return AIQueryResponse(
      answer: json['answer'] as String,
      visuals: (json['visuals'] as List<dynamic>?)
              ?.map((v) => VisualItem.fromJson(v as Map<String, dynamic>))
              .toList() ??
          [],
      modelUsed: json['model_used'] as String,
      sources: json['sources'] as List<dynamic>? ?? [],
    );
  }
}
```

---

## ⚠️ 5. Rate Limiting & Error Handling

### Rate Limiting (`HTTP 429 Too Many Requests`)
The backend enforces a sliding window rate limit (10 RAG queries per 60 seconds per user).
- When limit is exceeded, HTTP status `429` is returned with header `Retry-After: <seconds>`.
- Frontend should display: *"Rate limit exceeded. Please wait X seconds before asking another question."*

### Service Errors (`HTTP 503 Service Unavailable`)
If the AI service experiences a transient outage or quota issue, HTTP status `503` is returned.
- Frontend should handle `503` gracefully by allowing the user to tap *"Retry Query"*.

---

## 📝 6. Generated Examination Paper Visuals (`PaperQuestionResponse`)

In addition to tutor RAG queries, examination papers generated via `POST /api/v1/papers/generate` or retrieved via `GET /api/v1/papers/{paper_id}` contain structured question objects with deterministic SVG visuals.

### 6.1 Backend API Fields in Each Question

| Field | Type | Description |
| :--- | :--- | :--- |
| `visual_required` | `bool` | `true` if the question depends on a visual diagram/figure; `false` otherwise. |
| `visual_type` | `String?` | Visual classification (`"circuit"`, `"geometry"`, `"graph"`, `"diagram"`, `"chart"`). |
| `visual_title` | `String?` | Human-readable title for the figure (e.g. `"Simple DC Circuit"`). |
| `visual_caption` | `String?` | Optional explanatory caption for the visual. |
| `visual_spec` | `Map<String, dynamic>?` | Semantic JSON specification (points, nodes, connections, series). |
| `visual_svg` | `String?` | Deterministic SVG XML markup string ready for rendering. `null` if no visual or if generation failed. |

---

### 6.2 Complete Flutter Dart Data Model

```dart
class PaperQuestionModel {
  final String id;
  final int questionOrder;
  final String sectionName;
  final String questionType; // "MCQ", "SHORT_ANSWER", "LONG_ANSWER", "NUMERICAL"
  final String questionText;
  final int marks;
  final String difficulty; // "EASY", "MEDIUM", "HARD"
  final String sourceType; // "AI_GENERATED", "REFERENCE_REUSED", "REFERENCE_VARIATION"
  final bool isNumerical;

  // Internal choice grouping
  final String? choiceGroup; // e.g. "Q4"
  final String? alternativeLabel; // e.g. "a", "b"

  // Answer & solution fields
  final List<String>? mcqOptions;
  final String? correctAnswer;
  final String? expectedAnswer;
  final Map<String, dynamic>? numericalValues;
  final String? solutionExplanation;
  final String? unit;

  // Deterministic visual fields (Phase 3E/4A)
  final bool visualRequired;
  final String? visualType;
  final String? visualTitle;
  final String? visualCaption;
  final Map<String, dynamic>? visualSpec;
  final String? visualSvg;

  PaperQuestionModel({
    required this.id,
    required this.questionOrder,
    required this.sectionName,
    required this.questionType,
    required this.questionText,
    required this.marks,
    required this.difficulty,
    required this.sourceType,
    this.isNumerical = false,
    this.choiceGroup,
    this.alternativeLabel,
    this.mcqOptions,
    this.correctAnswer,
    this.expectedAnswer,
    this.numericalValues,
    this.solutionExplanation,
    this.unit,
    this.visualRequired = false,
    this.visualType,
    this.visualTitle,
    this.visualCaption,
    this.visualSpec,
    this.visualSvg,
  });

  factory PaperQuestionModel.fromJson(Map<String, dynamic> json) {
    return PaperQuestionModel(
      id: json['id'] as String,
      questionOrder: json['question_order'] as int? ?? 1,
      sectionName: json['section_name'] as String? ?? 'Section A',
      questionType: json['question_type'] as String? ?? 'SHORT_ANSWER',
      questionText: json['question_text'] as String? ?? '',
      marks: json['marks'] as int? ?? 1,
      difficulty: json['difficulty'] as String? ?? 'MEDIUM',
      sourceType: json['source_type'] as String? ?? 'AI_GENERATED',
      isNumerical: json['is_numerical'] as bool? ?? false,
      choiceGroup: json['choice_group'] as String?,
      alternativeLabel: json['alternative_label'] as String?,
      mcqOptions: (json['mcq_options'] as List<dynamic>?)
          ?.map((e) => e.toString())
          .toList(),
      correctAnswer: json['correct_answer'] as String?,
      expectedAnswer: json['expected_answer'] as String?,
      numericalValues: json['numerical_values'] is Map<String, dynamic>
          ? json['numerical_values'] as Map<String, dynamic>
          : null,
      solutionExplanation: json['solution_explanation'] as String?,
      unit: json['unit'] as String?,
      visualRequired: json['visual_required'] as bool? ?? false,
      visualType: json['visual_type'] as String?,
      visualTitle: json['visual_title'] as String?,
      visualCaption: json['visual_caption'] as String?,
      visualSpec: json['visual_spec'] is Map<String, dynamic>
          ? json['visual_spec'] as Map<String, dynamic>
          : null,
      visualSvg: json['visual_svg'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'question_order': questionOrder,
      'section_name': sectionName,
      'question_type': questionType,
      'question_text': questionText,
      'marks': marks,
      'difficulty': difficulty,
      'source_type': sourceType,
      'is_numerical': isNumerical,
      'choice_group': choiceGroup,
      'alternative_label': alternativeLabel,
      'mcq_options': mcqOptions,
      'correct_answer': correctAnswer,
      'expected_answer': expectedAnswer,
      'numerical_values': numericalValues,
      'solution_explanation': solutionExplanation,
      'unit': unit,
      'visual_required': visualRequired,
      'visual_type': visualType,
      'visual_title': visualTitle,
      'visual_caption': visualCaption,
      'visual_spec': visualSpec,
      'visual_svg': visualSvg,
    };
  }
}
```

---

### 6.3 Internal-Choice Alternatives Independence

When internal choice is configured (e.g. `Q4(a)` and `Q4(b)`), each alternative is received as a distinct `PaperQuestionModel` with:
- `choiceGroup == "Q4"`
- `alternativeLabel == "a"` vs `alternativeLabel == "b"`
- Each alternative possesses its own independent `visualType`, `visualSpec`, and `visualSvg`.

Frontend UI state should group by `choiceGroup` and render the specific visual attached to the active selected alternative.
