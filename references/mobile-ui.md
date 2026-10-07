# Mobile UI and component choices

Read for mobile screens, responsive layouts, touch interactions, or library recommendations. Start with the actual app and the user's target. Smaller browser dimensions do not make a Next.js page an iOS app.

## Establish the platform

Run `detect-project.py` against the application directory when needed; its `projects` are candidates derived from manifests/source, not proof of runnable apps. In a workspace, inspect the intended app's manifest and imports instead of selecting the root from a framework dev dependency. React Native commonly also declares React, which does not make it a DOM project. A `Package.swift` alone identifies a Swift package, not SwiftUI or an iOS deployment target; check source imports and project settings. A plain Dart `pubspec.yaml` is not proof of Flutter.

Keep the existing framework, router, primitives, and theme unless the requested change requires more. Distinguish a visual reference from a dependency to install. Do not introduce a new UI suite for one control already covered by the project.

These recommendations are external ecosystem references, not promised StyleKit `/api/assets` entries. Search the live catalog before claiming an asset exists; do not invent a `mobile` asset kind or depend on an unpublished `/mobile` page.

## Select a small, compatible set

Use official docs, the current package manifest, license, and maintenance statement before recommending or installing. Installed versions and platform support take priority over popularity. These are starting points checked on 2026-10-07, not a permanent ranking or an exhaustive catalog:

| Target | Starting points | Integration decision |
| --- | --- | --- |
| React / Next.js mobile web | [Ant Design Mobile](https://mobile.ant.design/), [Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog) | Ant Design Mobile supplies mobile web controls. Radix supplies dialog semantics and focus behavior; styling it at the bottom does not add drag gestures or snap points. Reuse existing primitives first. |
| Web carousel | [Blossom Carousel](https://blossom-carousel.com/docs/framework-guides/react-nextjs), [Swiper](https://swiperjs.com/react) | Start with native scrolling for a simple rail; use a library for required behavior. Blossom's browser-native scrolling does not mean native iOS components. |
| Vue mobile web | [Vant](https://vant-ui.github.io/vant/) | Check Vue version and component docs. Vue components cannot be imported as React DOM components. |
| React Native / Expo | [React Native Paper](https://oss.callstack.com/react-native-paper/), [React Native Bottom Sheet](https://gorhom.dev/react-native-bottom-sheet/) | Verify RN/Expo compatibility, theme/provider setup, and gesture/animation dependencies. DOM dialogs are not native sheets. |
| SwiftUI / iOS | [ChunUI](https://github.com/liseami/ChunUI), [ShipSwift](https://github.com/signerlabs/ShipSwift) | Inspect actual Swift APIs and deployment requirements; copy only appropriate, licensed components. These are not npm UI packages. |
| Flutter | Existing Flutter/Material/Cupertino widgets | Inspect the project's Dart dependencies and platform targets before proposing an additional suite. Web Tailwind recipes do not compile as Flutter widgets. |

When returning recommendations, say what fits this project, why, what must be configured, and link the source. If asked only for research, stop at usable recommendations; do not modify dependencies. When implementation is requested, implement the compatible choice within the authorized scope.

### ChunUI specifically

ChunUI is a SwiftUI design system. Its [package manifest](https://github.com/liseami/ChunUI/blob/main/Package.swift) currently specifies iOS 18.6 and Swift tools 6.2; verify these against the target before integration. Its README follows `main`, so choose an appropriate fixed revision for reproducibility. The [bundled usage reference](https://github.com/liseami/ChunUI/tree/main/skills/chunui) is useful for actual APIs; read the relevant part instead of inventing modifiers or adding another agent skill automatically.

For a browser project asking for a ChunUI-like feel, translate the visual direction (neutral surfaces, a restrained brand accent, tactile controls) into the existing Web stack. State that this is an adaptation; do not import SwiftUI or claim native sheet, haptic, or Metal behavior. For a real iOS project, retain platform typography and accessibility rather than copying fixed web font sizes.

## Design the interaction

Pick patterns that serve the task rather than putting every screen inside a decorative phone frame:

- **Reading/content:** readable measure, a clear title and metadata hierarchy, useful save/share states, navigation that leaves space for content.
- **Commerce:** variant choice, price/stock feedback, a reachable action, and an accessible selection sheet. Preserve choices when the sheet closes.
- **Tasks/tools:** information density suited to small screens, visible selection/completion state, useful empty/error states, and keyboard-safe inputs.

Use the style spec's visual intent, but adapt recipes to the runtime. A browser prototype is evidence of its own Web behavior; it does not validate a native library.

## Verify the mobile behavior

- Test representative narrow, middle, and wide sizes; 360/390/430 CSS px are useful Web samples, not universal device dimensions. Include long labels, text zoom, and landscape where relevant.
- Check content under fixed headers and bottom actions, safe-area insets, and software-keyboard overlap. Use the target platform's safe-area and keyboard APIs; browser emulation does not prove device behavior.
- Give touch actions comfortable hit areas and alternatives to hover or gesture-only controls. For Web, [WCAG 2.2 target-size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) is 24 by 24 CSS px or a documented exception; larger targets are preferable for primary actions.
- For a modal Web sheet, check accessible name, focus entry, containment, Escape, close control, and focus restoration. For native sheets, verify accessibility and dismissal with the native runtime.
- Test theme changes and reloads, loading/error states, and reduced motion. Keep SSR's first render deterministic before reading stored theme preferences.
- Use `eval-check.py` only for compatible static Web classes. Report native source review, successful compilation, simulator testing, and device testing separately; do not claim native validation from a browser screenshot or a static-class pass.
