const BOOLEAN_VALUES = new Set([
  "true",
  "t",
  "1",
  "True",
  "T",
  "TRUE",
  "yes",
  "y",
  "Yes",
  "Y",
  "YES",
  "false",
  "f",
  "0",
  "False",
  "F",
  "FALSE",
  "no",
  "n",
  "No",
  "N",
  "NO",
]);

export const formats = {
  boolean: (value) => typeof value === "string" && BOOLEAN_VALUES.has(value),
  integer: (value) => typeof value === "string" && /^-?\d+$/.test(value),
  number: (value) =>
    typeof value === "string" && /^-?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(value),
};
