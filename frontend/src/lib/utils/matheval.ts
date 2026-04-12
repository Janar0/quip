/**
 * Safe math expression evaluator — recursive descent parser.
 * Supports: x, named params, +, -, *, /, ^, (, ), sin, cos, tan, abs, sqrt, log, ln, exp, pi, e
 * NO eval() — fully parsed.
 */

const FUNCS: Record<string, (x: number) => number> = {
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  abs: Math.abs,
  sqrt: Math.sqrt,
  log: Math.log10,
  ln: Math.log,
  exp: Math.exp,
  ceil: Math.ceil,
  floor: Math.floor,
  round: Math.round,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  sinh: Math.sinh,
  cosh: Math.cosh,
  tanh: Math.tanh,
  sign: Math.sign,
};

const CONSTS: Record<string, number> = {
  pi: Math.PI,
  e: Math.E,
};

interface Token {
  type: 'num' | 'id' | 'op' | 'lparen' | 'rparen' | 'comma';
  value: string;
}

function tokenize(expr: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < expr.length) {
    const ch = expr[i];
    if (/\s/.test(ch)) { i++; continue; }
    if (/[0-9.]/.test(ch)) {
      let num = '';
      while (i < expr.length && /[0-9.eE]/.test(expr[i])) {
        num += expr[i++];
        // Handle negative exponent like 1e-5
        if ((expr[i - 1] === 'e' || expr[i - 1] === 'E') && expr[i] === '-') num += expr[i++];
      }
      tokens.push({ type: 'num', value: num });
    } else if (/[a-zA-Z_]/.test(ch)) {
      let id = '';
      while (i < expr.length && /[a-zA-Z0-9_]/.test(expr[i])) id += expr[i++];
      tokens.push({ type: 'id', value: id });
    } else if ('+-*/^'.includes(ch)) {
      tokens.push({ type: 'op', value: ch });
      i++;
    } else if (ch === '(') {
      tokens.push({ type: 'lparen', value: '(' });
      i++;
    } else if (ch === ')') {
      tokens.push({ type: 'rparen', value: ')' });
      i++;
    } else if (ch === ',') {
      tokens.push({ type: 'comma', value: ',' });
      i++;
    } else {
      i++; // skip unknown
    }
  }
  return tokens;
}

class Parser {
  tokens: Token[];
  pos = 0;
  vars: Record<string, number>;

  constructor(tokens: Token[], vars: Record<string, number>) {
    this.tokens = tokens;
    this.vars = vars;
  }

  peek(): Token | undefined { return this.tokens[this.pos]; }
  next(): Token { return this.tokens[this.pos++]; }

  parseExpr(): number { return this.parseAddSub(); }

  parseAddSub(): number {
    let left = this.parseMulDiv();
    while (this.peek()?.type === 'op' && (this.peek()!.value === '+' || this.peek()!.value === '-')) {
      const op = this.next().value;
      const right = this.parseMulDiv();
      left = op === '+' ? left + right : left - right;
    }
    return left;
  }

  parseMulDiv(): number {
    let left = this.parsePower();
    while (this.peek()?.type === 'op' && (this.peek()!.value === '*' || this.peek()!.value === '/')) {
      const op = this.next().value;
      const right = this.parsePower();
      left = op === '*' ? left * right : left / right;
    }
    return left;
  }

  parsePower(): number {
    let base = this.parseUnary();
    while (this.peek()?.type === 'op' && this.peek()!.value === '^') {
      this.next();
      const exp = this.parseUnary(); // right-associative
      base = Math.pow(base, exp);
    }
    return base;
  }

  parseUnary(): number {
    if (this.peek()?.type === 'op' && this.peek()!.value === '-') {
      this.next();
      return -this.parseUnary();
    }
    if (this.peek()?.type === 'op' && this.peek()!.value === '+') {
      this.next();
      return this.parseUnary();
    }
    return this.parseAtom();
  }

  parseAtom(): number {
    const t = this.peek();
    if (!t) throw new Error('Unexpected end of expression');

    if (t.type === 'num') {
      this.next();
      return parseFloat(t.value);
    }

    if (t.type === 'id') {
      this.next();
      const name = t.value.toLowerCase();

      // Function call
      if (this.peek()?.type === 'lparen' && name in FUNCS) {
        this.next(); // consume (
        const arg = this.parseExpr();
        if (this.peek()?.type === 'rparen') this.next();
        return FUNCS[name](arg);
      }

      // Constants
      if (name in CONSTS) return CONSTS[name];

      // Variables
      if (name in this.vars) return this.vars[name];

      throw new Error(`Unknown variable: ${t.value}`);
    }

    if (t.type === 'lparen') {
      this.next();
      const val = this.parseExpr();
      if (this.peek()?.type === 'rparen') this.next();
      return val;
    }

    throw new Error(`Unexpected token: ${t.value}`);
  }
}

/** Evaluate a math expression with given variables. Safe — no eval(). */
export function evaluate(expr: string, vars: Record<string, number> = {}): number {
  const tokens = tokenize(expr);
  if (tokens.length === 0) return 0;

  // Handle implicit multiplication: "2x" → "2*x", "2sin(x)" → "2*sin(x)", etc.
  const expanded: Token[] = [];
  for (let i = 0; i < tokens.length; i++) {
    expanded.push(tokens[i]);
    const cur = tokens[i];
    const nxt = tokens[i + 1];
    if (!nxt) continue;
    // Insert * between: num→id, num→lparen, rparen→id, rparen→lparen, rparen→num, id→lparen (only if not a function)
    const needsMul =
      (cur.type === 'num' && (nxt.type === 'id' || nxt.type === 'lparen')) ||
      (cur.type === 'rparen' && (nxt.type === 'id' || nxt.type === 'lparen' || nxt.type === 'num'));
    if (needsMul) expanded.push({ type: 'op', value: '*' });
  }

  const parser = new Parser(expanded, vars);
  return parser.parseExpr();
}
