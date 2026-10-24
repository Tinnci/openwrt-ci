/* Fault injection around patched upstream C excerpts, not real hardware. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

typedef uint32_t u32;
#define EXT_CSD_CARD_TYPE_HS 3
#define EXT_CSD_CARD_TYPE_HS200 (3 << 4)
#define EXT_CSD_CARD_TYPE_HS400 (3 << 6)
#define EXT_CSD_CARD_TYPE_HS400ES (1 << 8)
#define MMC_CAP2_HS200 (3U << 5)
#define MMC_CAP2_HS400 (3U << 15)
#define MMC_CAP2_HS400_ES (1U << 20)
#define MMC_CAP_8_BIT_DATA (1U << 6)
#define MMC_BUS_WIDTH_8 3
#define MMC_BUSMODE_OPENDRAIN 1
#define WARN_ON(condition) assert(!(condition))
#define pr_warn(...) do { warnings++; printf(__VA_ARGS__); } while (0)

enum { LEGACY, HS, HS200, HS400, HS400ES };
struct mmc_card;
struct mmc_host;
struct mmc_host_ops {
	int (*execute_hs400_tuning)(struct mmc_host *, struct mmc_card *);
};
struct mmc_host {
	u32 caps;
	u32 caps2;
	bool claimed;
	int doing_init_tune;
	struct { int bus_width; int timing; } ios;
	struct mmc_host_ops *ops;
	struct mmc_card *card;
};
struct mmc_card {
	struct mmc_host *host;
	unsigned int mmc_avail_type;
	struct { int rev; } ext_csd;
};
static struct mmc_card storage;
static bool jdcloud, card_hs200;
static int attempts, freed, power_cycles, warnings, width;
static int switch_error, es_error, es_tune_error, tune_error, retry_error;
static int discovery_error, feature_error, hs200_select_error;
static u32 expected_ocr;

static bool of_machine_is_compatible(const char *name)
{
	assert(!strcmp(name, "redmi,ax5-jdcloud"));
	return jdcloud;
}
static bool mmc_host_is_spi(struct mmc_host *host) { (void)host; return false; }
static void mmc_set_bus_mode(struct mmc_host *host, int mode)
{
	(void)host;
	assert(mode == MMC_BUSMODE_OPENDRAIN);
}
static bool mmc_can_ext_csd(struct mmc_card *card) { (void)card; return true; }
static bool mmc_card_hs200(struct mmc_card *card) { return card->host->ios.timing == HS200; }
static bool mmc_card_hs400es(struct mmc_card *card) { return card->host->ios.timing == HS400ES; }
static bool mmc_card_hs(struct mmc_card *card) { return card->host->ios.timing == HS; }
static int mmc_select_hs200(struct mmc_card *card)
{
	if (hs200_select_error && attempts == 1)
		return hs200_select_error;
	card->host->ios.timing = HS200;
	return 0;
}
static int mmc_select_hs(struct mmc_card *card) { card->host->ios.timing = HS; return 0; }
static int mmc_select_hs400es(struct mmc_card *card)
{
	if (es_error)
		return es_error;
	card->host->ios.timing = HS400ES;
	return 0;
}
static int mmc_hs200_tuning(struct mmc_card *card)
{
	(void)card;
	return attempts > 1 ? retry_error : tune_error;
}
static int mmc_select_hs400(struct mmc_card *card)
{
	if (!(card->mmc_avail_type & EXT_CSD_CARD_TYPE_HS400) ||
	    card->host->ios.bus_width != MMC_BUS_WIDTH_8)
		return 0;
	if (switch_error)
		return switch_error;
	card->host->ios.timing = HS400;
	return 0;
}
static int es_tuning(struct mmc_host *host, struct mmc_card *card)
{
	(void)host; (void)card;
	return es_tune_error;
}
static int mmc_select_bus_width(struct mmc_card *card) { return card->host->ios.bus_width; }
static int mmc_select_hs_ddr(struct mmc_card *card) { (void)card; return 0; }
static void mmc_set_bus_speed(struct mmc_card *card) { (void)card; }
static const char *mmc_hostname(struct mmc_host *host) { (void)host; return "mmc0"; }
static void mmc_remove_card(struct mmc_card *card) { assert(card == &storage); freed++; }
static void mmc_power_cycle(struct mmc_host *host, u32 ocr)
{
	assert(ocr == expected_ocr);
	assert(freed == 1 && !host->card);
	assert(!(host->caps2 & (MMC_CAP2_HS400 | MMC_CAP2_HS400_ES)));
	assert(!(host->caps & MMC_CAP_8_BIT_DATA));
	assert(!host->doing_init_tune);
	host->ios.timing = LEGACY;
	power_cycles++;
}

/* The runner inserts mock discovery/setup into explicit fixture gaps only.
 * Timing selection, failure flags, cleanup and the wrapper come from the patch.
 */
#include "mmc-patched.c"

static struct mmc_host fresh(void)
{
	static struct mmc_host_ops ops = { .execute_hs400_tuning = es_tuning };
	jdcloud = card_hs200 = true;
	attempts = freed = power_cycles = warnings = 0;
	switch_error = es_error = es_tune_error = tune_error = retry_error = 0;
	discovery_error = feature_error = hs200_select_error = 0;
	width = MMC_BUS_WIDTH_8;
	expected_ocr = 0x60000;
	memset(&storage, 0, sizeof(storage));
	return (struct mmc_host) {
		.claimed = true, .ops = &ops,
		.caps = MMC_CAP_8_BIT_DATA | 1,
		.caps2 = MMC_CAP2_HS200 | MMC_CAP2_HS400 | (1U << 17),
	};
}
static void recovered(struct mmc_host *host)
{
	assert(mmc_init_card(host, expected_ocr, NULL) == 0);
	assert(attempts == 2 && power_cycles == 1 && freed == 1 && warnings == 1);
	assert(host->card == &storage && host->ios.timing == HS200);
	assert(host->caps2 == (MMC_CAP2_HS200 | (1U << 17)));
	assert(host->caps == 1 && host->ios.bus_width == 2);
	assert(mmc_can_sleep(host->card));
}
static void failed_once(struct mmc_host *host, struct mmc_card *oldcard, int error)
{
	u32 caps = host->caps2;
	assert(mmc_init_card(host, expected_ocr, oldcard) == error);
	assert(attempts == 1 && power_cycles == 0 && warnings == 0);
	assert(host->caps2 == caps);
}

int main(void)
{
	struct mmc_host host = fresh();
	assert(mmc_init_card(&host, expected_ocr, NULL) == 0);
	assert(attempts == 1 && !power_cycles && !freed && !warnings);
	assert(host.ios.timing == HS400);

	host = fresh(); switch_error = -EIO; recovered(&host);
	host = fresh(); tune_error = -EILSEQ; recovered(&host);
	host = fresh(); host.caps2 |= MMC_CAP2_HS400_ES;
	es_error = -EBADMSG; recovered(&host);
	host = fresh(); host.caps2 |= MMC_CAP2_HS400_ES;
	es_tune_error = -ETIMEDOUT; recovered(&host);

	host = fresh(); host.caps2 &= ~MMC_CAP2_HS400; tune_error = -EILSEQ;
	failed_once(&host, NULL, -EILSEQ);
	host = fresh(); width = 2; host.caps &= ~MMC_CAP_8_BIT_DATA; tune_error = -EILSEQ;
	failed_once(&host, NULL, -EILSEQ);
	host = fresh(); jdcloud = false; switch_error = -EIO;
	failed_once(&host, NULL, -EIO);
	host = fresh(); switch_error = -EIO;
	failed_once(&host, &storage, -EIO); assert(!freed);
	host = fresh(); discovery_error = -ENODEV;
	failed_once(&host, NULL, -ENODEV); assert(!freed);
	host = fresh(); feature_error = -EIO;
	failed_once(&host, NULL, -EIO);
	host = fresh(); hs200_select_error = -EIO; recovered(&host);

	host = fresh(); host.caps2 &= ~MMC_CAP2_HS200;
	host.caps2 |= MMC_CAP2_HS400_ES; es_error = -EIO;
	failed_once(&host, NULL, -EIO);
	host = fresh(); card_hs200 = false;
	host.caps2 |= MMC_CAP2_HS400_ES; es_error = -EIO;
	failed_once(&host, NULL, -EIO);

	host = fresh(); switch_error = -EIO; retry_error = -ETIMEDOUT;
	assert(mmc_init_card(&host, expected_ocr, NULL) == -ETIMEDOUT);
	assert(attempts == 2 && power_cycles == 1 && freed == 2 && warnings == 1);
	assert(!host.card && !(host.caps2 & (MMC_CAP2_HS400 | MMC_CAP2_HS400_ES)));
	assert(!host.doing_init_tune);

	/* Preserve the pre-existing HS400ES -EBADMSG handling on resume/other boards. */
	host = fresh(); storage.host = &host;
	storage.mmc_avail_type = EXT_CSD_CARD_TYPE_HS400ES;
	es_error = -EBADMSG;
	assert(mmc_select_timing(&storage, false) == 0);
	puts("16 MMC fault-injection scenarios passed");
	return 0;
}
