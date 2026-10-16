// Pitch material: a chalk tactics board on paper. All markings are procedural (signed distance fields).
// 2-D simplex noise: Ashima Arts / Stefan Gustavson (MIT licence), https://github.com/ashima/webgl-noise

const NOISE = /* glsl */ `
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }
float snoise(vec2 v) {
  const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
  vec2 i = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod289(i);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
  m = m * m; m = m * m;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x = a0.x * x0.x + h.x * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}
`;

export const pitchVertex = /* glsl */ `
${NOISE}
uniform float uTime;
uniform float uLift;
varying vec2 vPitch;   // metres, origin at the centre spot (x along the length, y across)
void main() {
  vec3 p = position;                       // plane in XY before rotation; we read it as pitch coordinates
  vPitch = p.xy;
  float ripple = snoise(p.xy * 0.045 + uTime * 0.05) * 0.35 + snoise(p.xy * 0.13 - uTime * 0.03) * 0.08;
  p.z += ripple * (0.6 + uLift) + uLift * 1.5 * sin(p.x * 0.06 + uTime * 0.6);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}
`;

export const pitchFragment = /* glsl */ `
${NOISE}
uniform float uTime;
uniform vec2 uGapCenter;     // metres
uniform float uGapStrength;  // 0..1
uniform vec3 uTurf;
uniform vec3 uChalk;
uniform vec3 uRed;
varying vec2 vPitch;

float line(float d, float w) { return 1.0 - smoothstep(w * 0.5, w * 0.5 + 0.08, abs(d)); }

float sdBox(vec2 p, vec2 b) { vec2 d = abs(p) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }

void main() {
  vec2 p = vPitch;                         // x in [-52.5, 52.5], y in [-34, 34]
  float w = 0.12;                          // chalk line width in metres
  // mowing stripes along the length
  float stripe = step(0.5, fract((p.x + 52.5) / 10.5 * 0.5));
  vec3 col = uTurf * mix(0.92, 1.06, stripe);
  // paper fibre: fine noise over everything
  float fibre = snoise(p * 3.1) * 0.04 + snoise(p * 11.0) * 0.025;
  col *= 1.0 + fibre;

  float m = 0.0;
  m = max(m, line(sdBox(p, vec2(52.5, 34.0)), w));                 // touchlines and goal lines
  m = max(m, line(p.x, w) * step(abs(p.y), 34.0));                  // halfway line
  m = max(m, line(length(p) - 9.15, w));                            // centre circle
  m = max(m, 1.0 - smoothstep(0.18, 0.3, length(p)));               // centre spot
  for (int s = -1; s <= 1; s += 2) {
    float side = float(s);
    vec2 q = vec2(p.x - side * (52.5 - 8.25), p.y);
    m = max(m, line(sdBox(q, vec2(8.25, 20.16)), w));               // penalty boxes
    vec2 q6 = vec2(p.x - side * (52.5 - 2.75), p.y);
    m = max(m, line(sdBox(q6, vec2(2.75, 9.16)), w));                // six-yard boxes
    vec2 spot = vec2(side * (52.5 - 11.0), 0.0);
    m = max(m, 1.0 - smoothstep(0.15, 0.27, length(p - spot)));      // penalty spots
    float arc = line(length(p - spot) - 9.15, w) * step(16.5, abs(p.x - side * 52.5));  // arc outside the box
    m = max(m, arc);
  }
  // chalk is uneven: break the lines up with noise
  float chalkiness = 0.65 + 0.35 * smoothstep(-0.4, 0.6, snoise(p * 1.7 + 4.0));
  col = mix(col, uChalk, m * chalkiness);

  // the gap: a red Gaussian bleeding into the turf
  float g = exp(-dot(p - uGapCenter, p - uGapCenter) / (2.0 * 7.5 * 7.5)) * uGapStrength;
  g *= 0.85 + 0.15 * snoise(p * 0.8 + uTime * 0.2);
  col = mix(col, uRed, clamp(g, 0.0, 0.85));

  gl_FragColor = vec4(col, 1.0);
}
`;
