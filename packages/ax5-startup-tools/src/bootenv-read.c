/* SPDX-License-Identifier: MIT
 * Read-only AX5 environment inspection. No write API and no secret dump. */
#define _GNU_SOURCE
#define _DARWIN_C_SOURCE
#include <arpa/inet.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define ENV_SIZE 262144U
static int text_is(const char *path, const char *expected)
{
 char b[128]; FILE *f = fopen(path, "r");
 if (!f) return 0;
 char *s = fgets(b, sizeof b, f); fclose(f);
 if (!s) return 0;
 b[strcspn(b, "\r\n")] = 0;
 return strcmp(b, expected) == 0;
}
static uint32_t crc32(const unsigned char *p, size_t n)
{
 uint32_t c = 0xffffffffU;
 while (n--) {
  c ^= *p++;
  for (unsigned k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320U & (0U - (c & 1U)));
 }
 return ~c;
}
static void selected(const char *s, size_t length)
{
 static const char *keys[] = {"bootcmd", "bootdelay", "ipaddr", "netmask", "serverip", "custom_network"};
 for (size_t i = 0; i < sizeof keys / sizeof keys[0]; i++) {
  size_t n = strlen(keys[i]);
  if (length <= n || memcmp(s, keys[i], n) || s[n] != '=') continue;
  const char *v = s + n + 1; size_t count = length - n - 1;
  if (count > 63) { printf("%s=custom (redacted)\n", keys[i]); return; }
  char value[64]; memcpy(value, v, count); value[count] = 0;
  int valid = 0; struct in_addr addr;
  if (i == 0) valid = !strcmp(value, "bootipq");
  else if (i == 1) valid = count && strspn(value, "-0123456789") == count;
  else if (i == 5) valid = !strcmp(value, "1") || !strcmp(value, "0");
  else valid = inet_pton(AF_INET, value, &addr) == 1;
  printf("%s=%s\n", keys[i], valid ? value : "custom (redacted)"); return;
 }
}
int main(int argc, char **argv)
{
 const char *path = "/dev/mmcblk0p12"; int fixture = 0;
 if (argc == 3 && !strcmp(argv[1], "--file")) { path = argv[2]; fixture = 1; }
 else if (argc != 1) { fprintf(stderr, "Usage: ax5-bootenv-read [--file ENV_BACKUP]\n"); return 2; }
 if (!fixture && (!text_is("/tmp/sysinfo/board_name", "redmi,ax5-jdcloud") ||
     !text_is("/sys/class/block/mmcblk0p12/start", "12834") ||
     !text_is("/sys/class/block/mmcblk0p12/size", "512"))) {
  fprintf(stderr, "Refusing unverified board/partition layout\n"); return 1;
 }
 int fd = open(path, O_RDONLY | O_NOFOLLOW); struct stat st;
 if (fd < 0) { perror("open environment read-only"); return 1; }
 if (fstat(fd, &st) || (fixture ? (!S_ISREG(st.st_mode) || st.st_size != ENV_SIZE) : !S_ISBLK(st.st_mode))) {
  fprintf(stderr, "Unexpected environment device or size\n"); close(fd); return 1;
 }
 unsigned char *data = malloc(ENV_SIZE);
 if (!data) { close(fd); return 1; }
 size_t have = 0;
 while (have < ENV_SIZE) {
  ssize_t n = read(fd, data + have, ENV_SIZE - have);
  if (n <= 0) { fprintf(stderr, "Short environment read\n"); free(data); close(fd); return 1; }
  have += (size_t)n;
 }
 close(fd);
 uint32_t stored = data[0] | (uint32_t)data[1] << 8 | (uint32_t)data[2] << 16 | (uint32_t)data[3] << 24;
 if (stored != crc32(data + 4, ENV_SIZE - 4)) {
  puts("environment_crc=invalid"); free(data); return 1;
 }
 /* Reject malformed non-terminated entries even if the CRC is valid. */
 size_t at = 4;
 while (at < ENV_SIZE && data[at]) {
  unsigned char *end = memchr(data + at, 0, ENV_SIZE - at);
  if (!end) { fprintf(stderr, "Unterminated environment\n"); free(data); return 1; }
  at = (size_t)(end - data) + 1;
 }
 if (at == ENV_SIZE) { free(data); return 1; }
 puts("environment_crc=valid");
 for (at = 4; at < ENV_SIZE && data[at]; at += strlen((char *)data + at) + 1)
  selected((char *)data + at, strlen((char *)data + at));
 free(data); return 0;
}
