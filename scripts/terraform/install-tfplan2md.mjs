import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

/** 公式配布物を固定チェックサムで検証して指定ディレクトリへ展開する。 */
async function install() {
  const destination = process.argv[2];
  if (!destination) throw new Error('展開先ディレクトリを指定してください。');
  const config = JSON.parse(readFileSync(new URL('./tfplan2md.json', import.meta.url), 'utf8'));
  const platform = `${process.platform === 'darwin' ? 'macos' : process.platform}-${process.arch}`;
  const expectedChecksum = config.archives[platform];
  if (!expectedChecksum) throw new Error('このOS・CPUの配布物は固定されていません。');
  const archiveName = `tfplan2md_${config.version}_${platform}.tar.gz`;
  const response = await fetch(
    `https://github.com/oocx/tfplan2md/releases/download/v${config.version}/${archiveName}`,
    { signal: AbortSignal.timeout(60_000) },
  );
  if (!response.ok) throw new Error('公式配布物を取得できません。');
  const archive = Buffer.from(await response.arrayBuffer());
  if (createHash('sha256').update(archive).digest('hex') !== expectedChecksum) {
    throw new Error('配布物のチェックサムが一致しません。');
  }
  const temporaryDirectory = mkdtempSync(join(tmpdir(), 'tfplan2md-'));
  try {
    const archivePath = join(temporaryDirectory, archiveName);
    writeFileSync(archivePath, archive, { mode: 0o600 });
    mkdirSync(destination, { recursive: true, mode: 0o700 });
    execFileSync('tar', ['-xzf', archivePath, '-C', resolve(destination)], { stdio: 'pipe' });
  } finally {
    rmSync(temporaryDirectory, { recursive: true, force: true });
  }
}

try {
  await install();
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
