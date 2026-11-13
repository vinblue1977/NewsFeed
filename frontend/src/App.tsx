/** Placeholder page; the real screens come in Phase 3. */
export function greeting(name: string): string {
  return `Hello, ${name}`;
}

export function App() {
  return (
    <main>
      <h1>{greeting('News')}</h1>
    </main>
  );
}
