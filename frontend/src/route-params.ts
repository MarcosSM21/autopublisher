/** A route id: a positive integer, otherwise null ("not found" without calling the API). */
export function parseId(param: string | undefined): number | null {
  if (param === undefined || !/^[1-9]\d*$/.test(param)) {
    return null;
  }
  const id = Number(param);
  return Number.isSafeInteger(id) ? id : null;
}
