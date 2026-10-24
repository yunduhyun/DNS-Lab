/** AI 분석 Markdown을 표시용 HTML로 변환하고 허용한 서식만 남긴다. */
import { marked } from 'marked';
import sanitizeHtml from 'sanitize-html';

export function renderAnalysis(markdown) {
  return sanitizeHtml(marked.parse(markdown, { gfm: true, breaks: true }), {
    // 악성 분석 자료의 링크와 이미지가 외부 요청을 유발하지 않도록 서식 태그만 허용한다.
    allowedTags: [
      'p', 'br', 'strong', 'em', 'del', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'hr',
      'table', 'thead', 'tbody', 'tr', 'th', 'td'
    ],
    allowedAttributes: {},
    disallowedTagsMode: 'discard'
  });
}
