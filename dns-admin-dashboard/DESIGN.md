---
version: alpha
colors:
  surface: '#ffffff'
  text: '#34323a'
  muted: '#66616e'
  border: '#e4e3e7'
  selection: '#f5f1f9'
  primary: '#2d7131'
  danger: '#ac3434'
typography:
  body:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif'
  domain:
    fontFamily: 'ui-monospace, monospace'
rounded:
  panel: '6px'
  control: '4px'
omitted:
  - section: spacing
    reason: '기존 CSS의 화면별 간격을 유지한다.'
  - section: components
    reason: '프레임워크 컴포넌트 없이 CSS 클래스로 구현한다.'
---

## Overview

사내 DNS 분석 자료를 확인하는 한국어 관리자 도구다. 기존 흰색 바탕과 연보라 선택 표시를 유지한다. 검토 화면은 목록을 선택하고 옆의 근거를 읽는 작업대를 기준으로 구성한다. 장식과 애니메이션은 추가하지 않는다.

## Colors

`public/style.css`의 CSS 변수가 실제 값의 기준이다. surface는 --surface, text는 --text, muted는 --muted, border는 --border, selection은 --lavender-soft, primary는 --green-dark, danger는 --danger에 대응한다. 차단은 붉은색과 명확한 텍스트를 함께 사용한다. 상태와 의미를 색상만으로 전달하지 않는다.

## Typography

한국어 본문에는 시스템 글꼴을 사용하고 도메인 목록 식별자에는 고정폭 글꼴을 사용한다. 긴 도메인과 보고서 내용은 줄바꿈한다.

## Layout

전체 현황은 기존 표와 읽기 전용 보고서 모달을 사용한다. 검토 대상은 데스크톱에서 목록과 보고서를 나란히 표시한다. 1000px 이하에서는 위아래로 표시한다. 검토 보고서는 데스크톱에서 자체 스크롤한다. 허용과 차단 버튼은 보고서 상단 제목 옆에 표시한다. 모바일에서는 문서가 스크롤하고 보고서 상단 제목과 버튼이 화면 위쪽에 붙는다.

## Elevation & Depth

패널은 테두리로 구분하고 확인창은 브라우저 dialog를 사용한다.

## Shapes

기존 패널과 버튼의 작은 모서리 곡률을 유지한다.

## Components

버튼은 .button, 위험 결정은 .danger-button, 보고서는 reportContent(), 상태 표시는 labels, 시각 표시는 date()가 담당한다. 공통 스크롤 스타일은 public/style.css가 담당한다.

## Do's and Don'ts

차단 대상 지정과 실제 RPZ 적용 완료를 구분한다. 전체 현황에서는 검토 결정 버튼을 표시하지 않는다. 검토 흐름에 삭제를 섞지 않는다.
