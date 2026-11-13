import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

// Security: no HTML strings, no eval-like code. The CSP blocks these too; the lint stops them earlier.
const htmlSinks = ['innerHTML', 'outerHTML', 'insertAdjacentHTML'].map((property) => ({
  selector: `AssignmentExpression[left.property.name='${property}'], CallExpression[callee.property.name='${property}']`,
  message: `${property} can inject HTML; build elements with JSX instead.`,
}));

export default tseslint.config(
  { ignores: ['dist'] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  {
    languageOptions: { globals: globals.browser },
    rules: {
      eqeqeq: 'error',
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'no-script-url': 'error',
      'no-restricted-properties': [
        'error',
        { object: 'document', property: 'write', message: 'document.write can inject HTML.' },
        { object: 'document', property: 'writeln', message: 'document.writeln can inject HTML.' },
      ],
      'no-restricted-syntax': [
        'error',
        ...htmlSinks,
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: 'Raw HTML is not allowed.' },
        { selector: "JSXAttribute[name.name='href'][value.value=/^javascript:/i]", message: 'Script URLs are not allowed.' },
      ],
    },
  },
);
