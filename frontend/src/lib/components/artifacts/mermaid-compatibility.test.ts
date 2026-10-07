import { afterEach, beforeEach, expect, it } from 'vitest';
import mermaid from 'mermaid';

let originalBounds: PropertyDescriptor | undefined;

beforeEach(() => {
  // jsdom has no SVG layout engine; the renderer still executes its real
  // graph and math pipeline against a predictable measured label size.
  originalBounds = Object.getOwnPropertyDescriptor(SVGElement.prototype, 'getBBox');
  Object.defineProperty(SVGElement.prototype, 'getBBox', {
    configurable: true,
    value: () => ({ x: 0, y: 0, width: 120, height: 24 }),
  });
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', forceLegacyMathML: true });
});

afterEach(() => {
  if (originalBounds) Object.defineProperty(SVGElement.prototype, 'getBBox', originalBounds);
  else Reflect.deleteProperty(SVGElement.prototype, 'getBBox');
});

it('renders a diagram with a math label using the patched shared KaTeX dependency', async () => {
  const { svg } = await mermaid.render('math-dependency-compatibility',
    String.raw`flowchart LR; A["$$\frac{1}{2}$$"] --> B[Done]`);
  const result = document.createElement('div');
  result.innerHTML = svg;

  expect(result.querySelector('svg')).not.toBeNull();
  expect(result.querySelector('math')).not.toBeNull();
  expect(result.textContent).toContain('Done');
}, 10000);
