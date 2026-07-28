# Instruction Prompt Template 설계

- 문서 상태: `review`
- 마지막 검토일: 2026-07-28
- Template 상태: `design_completed_not_serialized`
- Tokenizer 변경: `forbidden`

## 공통 원칙

[확정] 아래 블록은 logical placeholder이며 실제 dataset record가 아니다. 현재 tokenizer special token을
추가하거나 ID를 변경하지 않는다. 최종 delimiter, whitespace, escaping, truncation, label mask와 template
fingerprint는 dataset·SFT 별도 승인 전에 확정해야 한다.

## Template family

### Base

```text
{{ text }}
```

Base는 instruction wrapper를 사용하지 않으며 immutable parent의 기존 입력 계약을 설명하는 비교 기준이다.

### Instruction

```text
{{#if system}}<SYSTEM>
{{ system }}
{{/if}}<INSTRUCTION>
{{ instruction }}
{{#if input}}<INPUT>
{{ input }}
{{/if}}<RESPONSE>
{{ output }}
```

### JSON

```text
<INSTRUCTION>
{{ instruction }}
<INPUT>
{{ input }}
<OUTPUT_SCHEMA>
{{ json_schema }}
<RESPONSE>
{{ output }}
```

응답은 승인된 JSON top-level type만 허용하고 앞뒤 설명 text를 포함하지 않는 것을 목표로 한다.

### Markdown

```text
<INSTRUCTION>
{{ instruction }}
<FORMAT_CONTRACT>
{{ markdown_contract }}
<RESPONSE>
{{ output }}
```

### Tool prompt

```text
<SYSTEM>
{{ permission_boundary }}
<TOOLS>
{{ tool_schemas }}
<INSTRUCTION>
{{ instruction }}
<RESPONSE>
{{ tool_or_text_output }}
```

Tool output은 실제 실행이 아니라 승인된 schema에 맞는 선택·argument 제안이다.

### Chat reservation

```text
{{ system }}
{{ conversation_history }}
{{ assistant_response }}
```

Chat serialization은 lineage만 예약한다. Instruct SFT template에 자동 포함하지 않으며 Chat 단계의 별도 ADR,
role mask, multi-turn truncation과 service decoding 승인이 필요하다.

## Escaping과 mask

- User-controlled text가 delimiter 또는 system block을 위조하지 못하도록 escaping/versioning을 정의한다.
- `system`, `instruction`, `input`, format/tool schema는 label `-100` 대상 후보다.
- `output`과 승인된 종료 token만 supervised label 대상 후보다.
- Empty output, response delimiter 중복과 EOS 누락은 fail closed한다.
- Metadata·license·source·quality·safety field는 prompt에 serialize하지 않는다.

## 미결정 사항

- [검증 필요] delimiter 문자열과 tokenizer 분절·충돌률
- [검증 필요] context budget과 field별 truncation 우선순위
- [검증 필요] loss mask·EOS 삽입·multi-example packing
- [검증 필요] system prompt 허용 source와 override 규칙

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-28 | Base·Instruction·JSON·Markdown·Tool·Chat placeholder template 설계 |
