// Papa Parse 5.7 ships without types. This covers the one call in
// csv-upload-modal.tsx: Papa.parse(file, { header, preview, complete }).
declare module "papaparse" {
  export interface ParseResult<T> {
    data: T[];
  }

  export interface ParseConfig<T> {
    header?: boolean;
    preview?: number;
    complete?: (results: ParseResult<T>) => void;
  }

  export interface Papa {
    parse<T>(file: File, config: ParseConfig<T>): void;
  }

  const Papa: Papa;
  export default Papa;
}
